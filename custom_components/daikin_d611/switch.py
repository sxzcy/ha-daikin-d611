"""Switch entities for Daikin DTA117D611 HD (Heat Exchanger) mute mode."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import HD_TYPES
from .coordinator import DaikinD611Coordinator
from .entity import DaikinD611Entity

if TYPE_CHECKING:
    from . import DaikinD611ConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinD611ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daikin D611 HD mute switch entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        DaikinD611HdMuteSwitch(coordinator, device_id)
        for device_id, device in coordinator.data.items()
        if device.device_type in HD_TYPES
    )


class DaikinD611HdMuteSwitch(DaikinD611Entity, SwitchEntity):
    """Daikin HD mute switch."""

    def __init__(self, coordinator: DaikinD611Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_name = "静音模式"
        self._attr_unique_id = f"{self.entity_unique_id}_mute_switch"

    @property
    def is_on(self) -> bool | None:
        mute = self.device.status.get("mute")
        return None if mute is None else mute == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_control_device(mute=1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_control_device(mute=0)
