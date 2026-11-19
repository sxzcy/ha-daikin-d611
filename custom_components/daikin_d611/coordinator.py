"""Pure-asyncio coordinator for Daikin DTA117D611."""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .cloud import DaikinCloudClient, parse_cloud_snapshot
from .codec import DaikinAuthError, DaikinError, first_value, format_error, to_int
from .const import (
    AIR_CON_TYPES,
    CONF_CONTROL_ACK_TIMEOUT,
    CONF_ENABLE_CLOUD_SNAPSHOT,
    CONF_GATEWAY,
    CONF_STATE_PRIORITY,
    CONF_TIMEOUT,
    DEFAULT_CONTROL_ACK_TIMEOUT,
    DEFAULT_ENABLE_CLOUD_SNAPSHOT,
    DEFAULT_GATEWAY,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STATE_PRIORITY,
    DEFAULT_TIMEOUT,
    DOMAIN,
    STATE_PRIORITY_LOCAL_FIRST,
    VAM_TYPES,
)
from .models import DaikinDevice, DaikinGateway
from .transport import DaikinLocalTransport

_LOGGER = logging.getLogger(__name__)

SOURCE_METADATA_KEYS = frozenset({
    "air_sensor_info_raw", "air_sensor_status_raw", "air_sensor_status_tags",
    "cloud_physics", "cloud_snapshot_available", "cloud_source",
    "composite_raw", "composite_tags", "last_cloud_refresh",
    "last_control_ack_body", "last_control_ack_cmd", "last_control_ack_request_id",
    "last_control_result", "last_control_time", "last_control_values",
    "last_local_refresh", "local_gateway", "local_gateway_available",
    "local_source", "raw", "state_sources", "state_stale",
})

CLOUD_SNAPSHOT_INTERVAL = timedelta(minutes=10)
WARNING_COOLDOWN = timedelta(minutes=5)
DELAYED_REFRESH_SECONDS = 15
FAILURE_GRACE_THRESHOLD = 3


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class DaikinD611Coordinator(DataUpdateCoordinator[dict[str, DaikinDevice]]):
    """Fetch cloud gateway metadata and local gateway device state asynchronously."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.gateway: DaikinGateway | None = None
        self.gateway_device_id: str | None = None
        self.nlc_id: str | None = None
        self._io_lock = asyncio.Lock()
        self._consecutive_failures = 0
        self._failure_grace_threshold = FAILURE_GRACE_THRESHOLD
        self._cached_devices: list[DaikinDevice] | None = None
        self._last_cloud_snapshot_at: datetime | None = None
        self._last_warning_at: dict[str, datetime] = {}
        self._poll_timeout = max(1.0, float(self._option(CONF_TIMEOUT, DEFAULT_TIMEOUT)))
        self.cloud = DaikinCloudClient(
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            timeout=self._poll_timeout,
            bootstrap_session=async_get_clientsession(hass),
        )
        self._delayed_refresh_task: asyncio.Task[None] | None = None
        update_interval = timedelta(seconds=int(self._option(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)))
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def last_cloud_snapshot_at(self) -> datetime | None:
        return self._last_cloud_snapshot_at

    @property
    def control_ack_timeout(self) -> float:
        return float(self._option(CONF_CONTROL_ACK_TIMEOUT, DEFAULT_CONTROL_ACK_TIMEOUT))

    def _option(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, self.entry.data.get(key, default))

    def _log_warning_limited(self, key: str, message: str, *args: Any) -> None:
        now = datetime.now(timezone.utc)
        if (prev := self._last_warning_at.get(key)) is None or now - prev >= WARNING_COOLDOWN:
            self._last_warning_at[key] = now
            _LOGGER.warning(message, *args)
        else:
            _LOGGER.debug(message, *args)

    def _cloud_snapshot_due(self) -> bool:
        if not bool(self._option(CONF_ENABLE_CLOUD_SNAPSHOT, DEFAULT_ENABLE_CLOUD_SNAPSHOT)):
            return False
        return (
            self._last_cloud_snapshot_at is None
            or not self.data
            or datetime.now(timezone.utc) - self._last_cloud_snapshot_at >= CLOUD_SNAPSHOT_INTERVAL
        )

    def _stale_devices_snapshot(self) -> dict[str, DaikinDevice]:
        return {
            dev_id: dev.clone(
                status={**dev.status, "local_gateway_available": False, "state_stale": True},
                available=dev.available,
                stable_id=dev.stable_physical_id,
            )
            for dev_id, dev in (self.data or {}).items()
        }

    async def _async_ensure_gateway(self) -> DaikinGateway:
        if self.gateway is not None and self.nlc_id:
            return self.gateway
        await self.cloud.async_ensure_login()
        host = self.entry.data.get(CONF_HOST)
        self.gateway = await self.cloud.async_discover_gateway(
            str(self.entry.data.get(CONF_GATEWAY, DEFAULT_GATEWAY)),
            host_override=str(host) if host else None,
            port_override=to_int(self.entry.data.get(CONF_PORT)),
        )
        if not self.nlc_id:
            info = await self.cloud.async_get_user_info()
            self.nlc_id = str(first_value(info.get("nlcId"), (info.get("userInfo") or {}).get("nlcId"), ""))
        if not self.nlc_id:
            raise DaikinError("Could not get nlcId")
        return self.gateway

    async def _async_rediscover_gateway(self) -> DaikinGateway:
        self.gateway = None
        self._cached_devices = None
        return await self._async_ensure_gateway()

    def _build_transport(self, gateway: DaikinGateway) -> DaikinLocalTransport:
        return DaikinLocalTransport(gateway, nlc_id=str(self.nlc_id), timeout=self._poll_timeout)

    @staticmethod
    def _source_map(status: dict[str, Any], source: str) -> dict[str, str]:
        return {k: source for k in status if k not in SOURCE_METADATA_KEYS and not k.endswith("_raw")}

    @staticmethod
    def _merge_status(base: dict[str, Any], extra: dict[str, Any], *, preserve_existing: bool = False) -> dict[str, Any]:
        merged = copy.deepcopy(base)
        for key, value in extra.items():
            if value in (None, ""):
                continue
            if key == "state_sources" and isinstance(value, dict):
                cur = dict(merged[key]) if isinstance(merged.get(key), dict) else {}
                inc = {k: v for k, v in value.items() if k not in cur} if preserve_existing else dict(value)
                merged[key] = {**cur, **inc}
            elif not (preserve_existing and key not in SOURCE_METADATA_KEYS and key in merged):
                merged[key] = copy.deepcopy(value)
        return merged

    async def _async_merge_cloud_snapshot(self, devices: list[DaikinDevice], statuses: dict[str, dict[str, Any]]) -> bool:
        gateway = await self._async_ensure_gateway()
        snapshot: dict[str, Any] = {}
        for candidate in dict.fromkeys(c for c in (gateway.key, gateway.mac) if c):
            try:
                snapshot = await self.cloud.async_get_ipbox_snapshot(candidate)
                break
            except DaikinAuthError:
                raise
            except DaikinError as exc:
                _LOGGER.debug("Failed to get ipbox snapshot for %s: %s", candidate, format_error(exc))
        if not snapshot:
            return False

        preserve = str(self._option(CONF_STATE_PRIORITY, DEFAULT_STATE_PRIORITY)) == STATE_PRIORITY_LOCAL_FIRST
        for dev_id, cloud_status in parse_cloud_snapshot(snapshot, devices, _utc_now_iso()).items():
            cloud_status["state_sources"] = self._source_map(cloud_status, "cloud")
            statuses[dev_id] = self._merge_status(
                statuses.get(dev_id, {}),
                cloud_status,
                preserve_existing=preserve,
            )
        return True

    @staticmethod
    def _has_local_control_status(devices: list[DaikinDevice], statuses: dict[str, dict[str, Any]]) -> bool:
        controllable = [d for d in devices if d.device_type in AIR_CON_TYPES or d.device_type in VAM_TYPES]
        return any(bool(statuses.get(d.unique_id)) for d in controllable) if controllable else bool(statuses)

    async def _async_poll_local(
        self, gateway: DaikinGateway, previous_data: dict[str, DaikinDevice], *, reuse_cached: bool,
    ) -> tuple[list[DaikinDevice], dict[str, dict[str, Any]]]:
        transport = self._build_transport(gateway)
        if reuse_cached and self._cached_devices:
            devices = list(self._cached_devices)
        else:
            try:
                devices = await transport.async_query_devices()
                self._cached_devices = [d.clone(status={}, available=True) for d in devices]
                self._last_warning_at.pop("room_list", None)
            except DaikinAuthError:
                raise
            except (DaikinError, TimeoutError, OSError) as exc:
                if not reuse_cached or not previous_data:
                    raise
                self._log_warning_limited("room_list", "Failed to refresh Daikin room list; using cached devices: %s", format_error(exc))
                devices = [d.clone(status={}, available=d.available) for d in previous_data.values()]
                self._cached_devices = list(devices)

        statuses = await transport.async_query_statuses(devices)
        if not self._has_local_control_status(devices, statuses):
            raise DaikinError(f"No local status returned from gateway {gateway.host}")
        return devices, statuses

    async def _async_refresh_devices(self) -> dict[str, DaikinDevice]:
        async with self._io_lock:
            previous_data = dict(self.data) if self.data else {}
            gateway = await self._async_ensure_gateway()
            local_error: Exception | None = None
            devices: list[DaikinDevice] = list(self._cached_devices or previous_data.values())
            try:
                devices, statuses = await self._async_poll_local(gateway, previous_data, reuse_cached=True)
                self._last_warning_at.pop("local_status", None)
            except DaikinAuthError:
                raise
            except (DaikinError, TimeoutError, OSError) as exc:
                self._log_warning_limited("local_status", "Local poll via %s failed; rediscovering: %s", gateway.host, format_error(exc))
                try:
                    gateway = await self._async_rediscover_gateway()
                    devices, statuses = await self._async_poll_local(gateway, previous_data, reuse_cached=False)
                    self._last_warning_at.pop("local_status", None)
                    self._last_warning_at.pop("local_status_retry", None)
                except DaikinAuthError:
                    raise
                except (DaikinError, TimeoutError, OSError) as retry_exc:
                    if not previous_data:
                        raise
                    local_error, statuses = retry_exc, {}
                    self._log_warning_limited("local_status_retry", "Local poll failed after rediscovery: %s", format_error(retry_exc))

            refreshed_at = _utc_now_iso()
            statuses = {
                dev_id: {
                    **st,
                    "last_local_refresh": refreshed_at,
                    "local_gateway": f"{gateway.host}:{gateway.port}",
                    "local_source": "socket",
                    "state_sources": self._source_map(st, "local"),
                }
                for dev_id, st in statuses.items() if st
            }
            cloud_attempted = self._cloud_snapshot_due()
            if cloud_attempted:
                try:
                    if await self._async_merge_cloud_snapshot(devices, statuses):
                        self._last_cloud_snapshot_at = datetime.now(timezone.utc)
                        self._last_warning_at.pop("cloud_snapshot", None)
                except DaikinAuthError:
                    raise
                except (DaikinError, TimeoutError, OSError) as exc:
                    self._log_warning_limited("cloud_snapshot", "Cloud snapshot refresh failed; using local state: %s", format_error(exc))

            if local_error is not None and not any(s.get("last_local_refresh") or s.get("last_cloud_refresh") for s in statuses.values()):
                raise local_error

            result: dict[str, DaikinDevice] = {}
            for template in devices:
                update = copy.deepcopy(statuses.get(template.unique_id, {}))
                fresh_local, fresh_cloud = bool(update.get("last_local_refresh")), bool(update.get("last_cloud_refresh"))
                previous = previous_data.get(template.unique_id)
                update["local_gateway_available"] = fresh_local
                update["cloud_snapshot_available"] = (
                    fresh_cloud if (cloud_attempted or previous is None) else bool(previous.status.get("cloud_snapshot_available"))
                )
                update["state_stale"] = not (fresh_local or fresh_cloud)
                merged = {**copy.deepcopy(previous.status if previous is not None else template.status), **update}
                snapshot = template.clone(
                    status=merged,
                    available=not merged.get("state_stale", False),
                    stable_id=previous.stable_physical_id if previous is not None else None,
                )
                result[snapshot.unique_id] = snapshot
            return result

    async def _async_update_data(self) -> dict[str, DaikinDevice]:
        try:
            data = await self._async_refresh_devices()
        except DaikinAuthError as exc:
            raise ConfigEntryAuthFailed(format_error(exc)) from exc
        except (DaikinError, TimeoutError, OSError) as exc:
            if not self.data:
                raise UpdateFailed(format_error(exc)) from exc
            self._consecutive_failures += 1
            if self._consecutive_failures > self._failure_grace_threshold:
                raise UpdateFailed(format_error(exc)) from exc
            self._log_warning_limited(
                "update", "Daikin D611 update failed (%s/%s); keeping stale data: %s",
                self._consecutive_failures, self._failure_grace_threshold, format_error(exc),
            )
            return self._stale_devices_snapshot()
        self._consecutive_failures = 0
        return data

    def _apply_optimistic_status(self, device_id: str, values: dict[str, Any], control_result: dict[str, Any] | None = None) -> None:
        if not self.data or device_id not in self.data:
            return
        device = self.data[device_id]
        status: dict[str, Any] = {}
        if "switch" in values:
            status["switch"] = values["switch"]
            if device.device_type in VAM_TYPES:
                status["switches"] = values["switch"]
        for src, dst in (("mode", "mode"), ("air_flow", "air_flow"), ("temperature", "target_temperature")):
            if src in values:
                status[dst] = values[src]
        if not status:
            return

        status.update({
            "last_control_time": _utc_now_iso(),
            "last_control_result": (control_result or {}).get("result") or "optimistic_local_command_sent",
            "last_control_ack_cmd": (control_result or {}).get("ack_cmd"),
            "last_control_ack_body": (control_result or {}).get("ack_body"),
            "last_control_ack_request_id": (control_result or {}).get("ack_request_id"),
            "last_control_values": dict(values),
            "local_gateway_available": True,
            "state_stale": False,
        })
        status["state_sources"] = self._source_map(status, "optimistic")
        updated = dict(self.data)
        updated[device_id] = device.clone(
            status=self._merge_status(device.status, status), available=True, stable_id=device.stable_physical_id,
        )
        self.async_set_updated_data(updated)

    async def _async_delayed_refresh(self) -> None:
        await asyncio.sleep(DELAYED_REFRESH_SECONDS)
        await self.async_request_refresh()

    def _schedule_delayed_refresh(self) -> None:
        self.cancel_delayed_refresh()
        self._delayed_refresh_task = self.hass.async_create_task(self._async_delayed_refresh())

    def cancel_delayed_refresh(self) -> None:
        if self._delayed_refresh_task and not self._delayed_refresh_task.done():
            self._delayed_refresh_task.cancel()
        self._delayed_refresh_task = None

    async def async_shutdown(self) -> None:
        """Cancel pending tasks and release cloud mTLS resources."""
        self.cancel_delayed_refresh()
        await self.cloud.async_close()
        if (parent_shutdown := getattr(super(), "async_shutdown", None)) is not None:
            await parent_shutdown()

    async def async_control_device(self, device_id: str, **values: Any) -> None:
        """Send a local TCP control command without duplicating commands on ACK timeout."""
        async with self._io_lock:
            device = (self.data or {}).get(device_id)
            if device is None:
                raise DaikinError(f"Unknown Daikin device: {device_id}")
            gateway = await self._async_ensure_gateway()
            try:
                result = await self._build_transport(gateway).async_control_device(
                    device, ack_timeout=self.control_ack_timeout, **values,
                )
            except DaikinAuthError:
                raise
            except (DaikinError, TimeoutError, OSError) as exc:
                _LOGGER.warning("Control via %s failed before send; rediscovering gateway: %s", gateway.host, format_error(exc))
                gateway = await self._async_rediscover_gateway()
                try:
                    result = await self._build_transport(gateway).async_control_device(
                        device, ack_timeout=max(self.control_ack_timeout, 5.0), **values,
                    )
                except DaikinAuthError:
                    raise
                except (DaikinError, TimeoutError, OSError) as retry_exc:
                    raise DaikinError(f"Control command failed after gateway rediscovery: {format_error(retry_exc)}") from retry_exc

            outcome = result.get("result")
            if outcome == "sent_ack_timeout":
                _LOGGER.debug("Control command for %s sent cleanly but ACK timed out; skipping duplicate resend", device_id)
            elif outcome not in {"accepted", "sent_no_ack_configured"}:
                raise DaikinError(f"Control command was not accepted: {result}")

        self._apply_optimistic_status(device_id, values, result)
        self._schedule_delayed_refresh()
