"""Base entity for Daikin DTA117D611."""

from __future__ import annotations

from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .codec import DaikinAuthError, DaikinError, format_error
from .const import CONF_USE_STABLE_IDS, DEFAULT_USE_STABLE_IDS, DOMAIN
from .coordinator import DaikinD611Coordinator
from .models import DaikinDevice


class DaikinD611Entity(CoordinatorEntity[DaikinD611Coordinator]):
    """Base Daikin DTA117D611 coordinator entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DaikinD611Coordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        device = self.device
        self._attr_unique_id = self.entity_unique_id
        device_identifier = device.stable_physical_id if self._use_stable_ids else device.unique_id
        device_info_kwargs: dict[str, Any] = {
            "identifiers": {(DOMAIN, device_identifier)},
            "name": device.stable_name,
            "manufacturer": "Daikin",
            "model": f"DTA117D611 {device.device_type_name}",
        }
        if coordinator.gateway_device_id:
            device_info_kwargs["via_device_id"] = coordinator.gateway_device_id
        self._attr_device_info = DeviceInfo(**device_info_kwargs)

    @property
    def device(self) -> DaikinDevice:
        return self.coordinator.data[self.device_id]

    @property
    def entity_unique_id(self) -> str:
        return self.device.stable_physical_id if self._use_stable_ids else self.device.unique_id

    @property
    def _use_stable_ids(self) -> bool:
        return bool(self.coordinator.entry.options.get(CONF_USE_STABLE_IDS, DEFAULT_USE_STABLE_IDS))

    @property
    def available(self) -> bool:
        return super().available and self.device_id in self.coordinator.data and self.device.available

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = self.device
        attributes: dict[str, Any] = {
            "room_id": device.room_id,
            "device_type": device.device_type_name,
            "unit": device.unit,
        }
        if device.room_alias or device.room_name:
            attributes["room"] = device.room_alias or device.room_name
        if "state_stale" in device.status:
            attributes["state_stale"] = bool(device.status["state_stale"])
        return attributes

    async def _async_control_device(self, **values: Any) -> None:
        try:
            await self.coordinator.async_control_device(self.device_id, **values)
        except DaikinAuthError as exc:
            entry = self.coordinator.entry
            if hasattr(entry, "async_start_reauth"):
                entry.async_start_reauth(self.coordinator.hass)
            raise HomeAssistantError(f"Authentication failed: {format_error(exc)}") from exc
        except (DaikinError, TimeoutError, OSError) as exc:
            raise HomeAssistantError(f"Failed to control Daikin device: {format_error(exc)}") from exc
