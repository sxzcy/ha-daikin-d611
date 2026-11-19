"""Diagnostics support for Daikin DTA117D611."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import DaikinD611Coordinator

if TYPE_CHECKING:
    from . import DaikinD611ConfigEntry

TO_REDACT = frozenset({
    CONF_USERNAME,
    CONF_PASSWORD,
    "token",
    "accessToken",
    "access_token",
    "device_id",
    "gatewayKey",
    "gatewayMac",
    "key",
    "mac",
    "host",
    "socketIp",
    "local_gateway",
    "home_id",
    "homeId",
    "nlc_id",
    "nlcId",
    "push_id",
    "pushId",
    "terminalMac",
    "terminal_mac",
    "serial_no",
    "device_no",
    "air_sensor_mac",
    "cloud_key",
    "composite_serial",
    "raw",
    "raw_status",
    "air_sensor_info_raw",
    "air_sensor_status_raw",
    "composite_raw",
    "stable_physical_id",
    "status_json",
    "last_control_ack_body",
})


def _device_diagnostics(coordinator: DaikinD611Coordinator) -> list[dict[str, Any]]:
    return [
        {
            "device_id": device_id,
            "stable_physical_id": device.stable_physical_id,
            "name": device.stable_name,
            "room_id": device.room_id,
            "room_name": device.room_name,
            "room_alias": device.room_alias,
            "device_type": device.device_type,
            "device_type_name": device.device_type_name,
            "unit": device.unit,
            "available": device.available,
            "status": device.status,
        }
        for device_id, device in (coordinator.data or {}).items()
    ]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: DaikinD611ConfigEntry,
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator: DaikinD611Coordinator | None = getattr(entry, "runtime_data", None)
    data: dict[str, Any] = {
        "entry": {
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "gateway": None,
        "devices": [],
    }
    if coordinator is not None:
        data["gateway"] = asdict(coordinator.gateway) if coordinator.gateway is not None else None
        data["devices"] = _device_diagnostics(coordinator)
        data["last_update_success"] = coordinator.last_update_success
        data["last_exception"] = str(coordinator.last_exception) if coordinator.last_exception else None
        data["consecutive_failures"] = coordinator.consecutive_failures
        data["last_cloud_snapshot_at"] = (
            coordinator.last_cloud_snapshot_at.isoformat()
            if coordinator.last_cloud_snapshot_at is not None
            else None
        )
    return async_redact_data(data, TO_REDACT)
