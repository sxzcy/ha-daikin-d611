"""Diagnostics support for Daikin DTA117D611."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import DaikinD611Coordinator

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    "token",
    "accessToken",
    "access_token",
    "gatewayKey",
    "gatewayMac",
    "mac",
    "terminalMac",
    "terminal_mac",
    "serial_no",
    "device_no",
    "air_sensor_mac",
    "cloud_key",
    "raw",
    "raw_status",
    "status_json",
    "last_control_ack_body",
}


def _device_diagnostics(coordinator: DaikinD611Coordinator) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for device_id, device in coordinator.data.items():
        devices.append(
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
        )
    return devices


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    coordinator: DaikinD611Coordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
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
    return async_redact_data(data, TO_REDACT)
