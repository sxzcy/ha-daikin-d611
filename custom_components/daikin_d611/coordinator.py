"""Coordinator for Daikin DTA117D611."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DaikinCloudClient, DaikinError, DaikinSocketClient, first_value, to_int, to_list
from .const import (
    AIR_CON_TYPES,
    AIR_SENSOR_TYPES,
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

_LOGGER = logging.getLogger(__name__)

SOURCE_METADATA_KEYS = {
    "air_sensor_info_raw",
    "air_sensor_status_raw",
    "air_sensor_status_tags",
    "cloud_physics",
    "cloud_source",
    "composite_raw",
    "composite_tags",
    "last_cloud_refresh",
    "last_control_result",
    "last_control_time",
    "last_control_values",
    "last_control_ack_body",
    "last_control_ack_cmd",
    "last_control_ack_request_id",
    "last_local_refresh",
    "local_gateway_available",
    "local_gateway",
    "local_source",
    "cloud_snapshot_available",
    "raw",
    "state_sources",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class DaikinD611Coordinator(DataUpdateCoordinator[dict[str, DaikinDevice]]):
    """Fetch cloud gateway metadata and local gateway device state."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.gateway: DaikinGateway | None = None
        self.nlc_id: str | None = None
        self.cloud = DaikinCloudClient(
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            timeout=float(self._option(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
        )
        self._delayed_refresh_task: asyncio.Task | None = None
        update_interval = timedelta(seconds=int(self._option(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

    @property
    def timeout(self) -> float:
        return float(self._option(CONF_TIMEOUT, DEFAULT_TIMEOUT))

    @property
    def control_ack_timeout(self) -> float:
        return float(self._option(CONF_CONTROL_ACK_TIMEOUT, DEFAULT_CONTROL_ACK_TIMEOUT))

    def _option(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, self.entry.data.get(key, default))

    def _cloud_snapshot_enabled(self) -> bool:
        return bool(self._option(CONF_ENABLE_CLOUD_SNAPSHOT, DEFAULT_ENABLE_CLOUD_SNAPSHOT))

    def _state_priority(self) -> str:
        return str(self._option(CONF_STATE_PRIORITY, DEFAULT_STATE_PRIORITY))

    def _host_override(self) -> str | None:
        host = self.entry.data.get(CONF_HOST)
        return str(host) if host else None

    def _port_override(self) -> int | None:
        return to_int(self.entry.data.get(CONF_PORT))

    def _ensure_gateway(self) -> DaikinGateway:
        if self.gateway is not None and self.nlc_id:
            return self.gateway
        self.cloud.ensure_login()
        self.gateway = self.cloud.discover_gateway(
            str(self.entry.data.get(CONF_GATEWAY, DEFAULT_GATEWAY)),
            host_override=self._host_override(),
            port_override=self._port_override(),
        )
        if not self.nlc_id:
            user_info = self.cloud.get_user_info()
            self.nlc_id = str(first_value(user_info.get("nlcId"), (user_info.get("userInfo") or {}).get("nlcId"), ""))
        if not self.nlc_id:
            raise DaikinError("Could not get nlcId")
        return self.gateway

    def _socket_client(self) -> DaikinSocketClient:
        gateway = self._ensure_gateway()
        return DaikinSocketClient(gateway, nlc_id=str(self.nlc_id), timeout=self.timeout)

    @staticmethod
    def _merge_status(
        base: dict[str, Any],
        extra: dict[str, Any],
        *,
        preserve_existing_values: bool = False,
    ) -> dict[str, Any]:
        merged = dict(base)
        for key, value in extra.items():
            if value in (None, ""):
                continue
            if key == "state_sources" and isinstance(value, dict):
                existing = merged.get(key)
                current_sources = existing if isinstance(existing, dict) else {}
                if preserve_existing_values:
                    incoming_sources = {
                        source_key: source_value
                        for source_key, source_value in value.items()
                        if source_key not in current_sources
                    }
                else:
                    incoming_sources = value
                merged[key] = {**current_sources, **incoming_sources}
                continue
            if preserve_existing_values and key not in SOURCE_METADATA_KEYS and key in merged:
                continue
            merged[key] = value
        return merged

    @staticmethod
    def _source_map(status: dict[str, Any], source: str) -> dict[str, str]:
        return {
            key: source
            for key in status
            if key not in SOURCE_METADATA_KEYS and not key.endswith("_raw")
        }

    @classmethod
    def _annotate_local_status(
        cls,
        status: dict[str, Any],
        refreshed_at: str,
        gateway: DaikinGateway,
    ) -> dict[str, Any]:
        if not status:
            return status
        return {
            **status,
            "last_local_refresh": refreshed_at,
            "local_gateway": f"{gateway.host}:{gateway.port}",
            "local_source": "socket",
            "state_sources": cls._source_map(status, "local"),
        }

    @classmethod
    def _cloud_status_for_item(cls, item: dict[str, Any], refreshed_at: str | None = None) -> dict[str, Any]:
        status = item.get("status") if isinstance(item.get("status"), dict) else {}
        physics = item.get("physics") if isinstance(item.get("physics"), dict) else {}
        filters = item.get("filter") if isinstance(item.get("filter"), dict) else {}
        cloud: dict[str, Any] = {
            **status,
            "cloud_key": item.get("key"),
            "cloud_online": item.get("online"),
            "cloud_physics": physics,
        }
        if item.get("key") and str(item["key"]).startswith("SENSOR:"):
            cloud["sensor_temperature"] = cloud.get("temp")
        elif "temp" in cloud:
            cloud["target_temperature"] = cloud["temp"]
        if "switches" in cloud:
            cloud["switch"] = cloud["switches"]
        if "volume" in cloud:
            cloud["air_flow"] = cloud["volume"]
        for key, value in filters.items():
            cloud[f"filter_{key.removeprefix('filter_')}"] = value
        if refreshed_at:
            cloud["last_cloud_refresh"] = refreshed_at
            cloud["cloud_source"] = "snapshot"
        cloud["state_sources"] = cls._source_map(cloud, "cloud")
        return cloud

    @staticmethod
    def _normalize_key(value: Any) -> str:
        return str(value or "").replace(":", "").replace("-", "").casefold()

    def _merge_cloud_snapshot(self, devices: list[DaikinDevice], statuses: dict[str, dict[str, Any]]) -> None:
        if not self._cloud_snapshot_enabled():
            return
        gateway = self._ensure_gateway()
        candidates = [gateway.key]
        if gateway.mac and gateway.mac != gateway.key:
            candidates.append(gateway.mac)

        snapshot: dict[str, Any] = {}
        last_error: Exception | None = None
        for candidate in candidates:
            if not candidate:
                continue
            try:
                snapshot = self.cloud.get_ipbox_snapshot(candidate)
                break
            except DaikinError as exc:
                last_error = exc
                _LOGGER.debug("Failed to get ipbox snapshot for %s", candidate, exc_info=True)
        if not snapshot:
            if last_error:
                _LOGGER.debug("No ipbox snapshot available: %s", last_error)
            return
        refreshed_at = _utc_now_iso()

        online_by_key: dict[str, Any] = {}
        for ipbox in snapshot.get("ipbox", []):
            if not isinstance(ipbox, dict):
                continue
            for sub_item in ipbox.get("sub", []):
                if isinstance(sub_item, dict) and sub_item.get("device_key"):
                    online_by_key[str(sub_item["device_key"])] = sub_item.get("online")

        indoor_items = [item for item in snapshot.get("indoor", []) if isinstance(item, dict)]
        vam_raw = to_list(snapshot.get("mini_vam")) + to_list(snapshot.get("vam"))
        vam_items = [item for item in vam_raw if isinstance(item, dict)]
        sensor_items = [item for item in snapshot.get("sensor", []) if isinstance(item, dict)]

        for device in devices:
            item = self._match_cloud_item(device, indoor_items, vam_items, sensor_items)
            if item is None:
                continue
            cloud_key = item.get("key")
            if item.get("online") is None and cloud_key in online_by_key:
                item = {**item, "online": online_by_key[str(cloud_key)]}
            preserve_existing = self._state_priority() == STATE_PRIORITY_LOCAL_FIRST
            statuses[device.unique_id] = self._merge_status(
                statuses.get(device.unique_id, {}),
                self._cloud_status_for_item(item, refreshed_at),
                preserve_existing_values=preserve_existing,
            )

    def _match_cloud_item(
        self,
        device: DaikinDevice,
        indoor_items: list[dict[str, Any]],
        vam_items: list[dict[str, Any]],
        sensor_items: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if device.device_type in AIR_CON_TYPES:
            candidates = indoor_items
        elif device.device_type in VAM_TYPES:
            candidates = vam_items
        elif device.device_type in AIR_SENSOR_TYPES:
            candidates = sensor_items
        else:
            return None

        device_key = self._normalize_key(device.name)
        device_alias = self._normalize_key(device.alias)
        for item in candidates:
            physics = item.get("physics") if isinstance(item.get("physics"), dict) else {}
            socket_room_id = to_int(physics.get("socket_room_id"))
            center_address = to_int(physics.get("center_address"))
            if socket_room_id == device.room_id or center_address == device.room_id - 1:
                return item

            cloud_parts = [
                item.get("key"),
                physics.get("serial_no"),
                physics.get("mac"),
                physics.get("device_no"),
            ]
            haystack = " ".join(self._normalize_key(part) for part in cloud_parts)
            if device_key and device_key in haystack:
                return item
            if device_alias and device_alias in haystack:
                return item
        return None

    def _refresh_sync(self) -> dict[str, DaikinDevice]:
        socket_client = self._socket_client()
        devices = socket_client.query_devices()
        statuses = socket_client.query_statuses(devices)
        refreshed_at = _utc_now_iso()
        statuses = {
            device_id: self._annotate_local_status(status, refreshed_at, socket_client.gateway)
            for device_id, status in statuses.items()
        }
        self._merge_cloud_snapshot(devices, statuses)
        result: dict[str, DaikinDevice] = {}
        for device in devices:
            statuses.setdefault(device.unique_id, {})
            statuses[device.unique_id]["local_gateway_available"] = bool(statuses[device.unique_id].get("last_local_refresh"))
            statuses[device.unique_id]["cloud_snapshot_available"] = bool(statuses[device.unique_id].get("last_cloud_refresh"))
            previous = self.data.get(device.unique_id) if self.data else None
            if previous is not None:
                device.status = {**previous.status, **statuses.get(device.unique_id, {})}
            else:
                device.status = statuses.get(device.unique_id, device.status)
            result[device.unique_id] = device
        return result

    async def _async_update_data(self) -> dict[str, DaikinDevice]:
        try:
            return await self.hass.async_add_executor_job(self._refresh_sync)
        except DaikinError as exc:
            raise UpdateFailed(str(exc)) from exc

    def _control_sync(self, device_id: str, values: dict[str, Any]) -> dict[str, Any]:
        device = self.data[device_id]
        return self._socket_client().control_device(device, ack_timeout=self.control_ack_timeout, **values)

    def _apply_optimistic_status(
        self,
        device_id: str,
        values: dict[str, Any],
        control_result: dict[str, Any] | None = None,
    ) -> None:
        if not self.data or device_id not in self.data:
            return

        device = self.data[device_id]
        status: dict[str, Any] = {}
        if "switch" in values:
            status["switch"] = values["switch"]
            if device.device_type in VAM_TYPES:
                status["switches"] = values["switch"]
        if "mode" in values:
            status["mode"] = values["mode"]
        if "air_flow" in values:
            status["air_flow"] = values["air_flow"]
        if "temperature" in values:
            status["target_temperature"] = values["temperature"]

        if not status:
            return
        now = _utc_now_iso()
        status["last_control_time"] = now
        if control_result:
            status["last_control_result"] = control_result.get("result") or "local_command_sent"
            status["last_control_ack_cmd"] = control_result.get("ack_cmd")
            status["last_control_ack_body"] = control_result.get("ack_body")
            status["last_control_ack_request_id"] = control_result.get("ack_request_id")
        else:
            status["last_control_result"] = "optimistic_local_command_sent"
        status["last_control_values"] = dict(values)
        status["state_sources"] = self._source_map(status, "optimistic")
        device.status = self._merge_status(device.status, status)
        self.async_set_updated_data(dict(self.data))

    async def _async_delayed_refresh(self) -> None:
        await asyncio.sleep(15)
        await self.async_request_refresh()

    def _schedule_delayed_refresh(self) -> None:
        if self._delayed_refresh_task and not self._delayed_refresh_task.done():
            self._delayed_refresh_task.cancel()
        self._delayed_refresh_task = self.hass.async_create_task(self._async_delayed_refresh())

    async def async_control_device(self, device_id: str, **values: Any) -> None:
        """Send a local socket control command, then refresh state."""

        control_result = await self.hass.async_add_executor_job(self._control_sync, device_id, values)
        self._apply_optimistic_status(device_id, values, control_result)
        self._schedule_delayed_refresh()
