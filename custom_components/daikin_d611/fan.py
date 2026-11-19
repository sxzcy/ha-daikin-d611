"""Fan entities for Daikin DTA117D611 VAM / Mini-VAM devices."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import VAM_TYPES
from .coordinator import DaikinD611Coordinator
from .entity import DaikinD611Entity
from .mappings import VAM_MODES, VAM_MODE_VALUES

if TYPE_CHECKING:
    from . import DaikinD611ConfigEntry

AIR_FLOW_TO_PERCENT: dict[int, int] = {1: 25, 2: 50, 3: 75, 4: 100}
TURN_ON_FEATURE = getattr(FanEntityFeature, "TURN_ON", 0)
TURN_OFF_FEATURE = getattr(FanEntityFeature, "TURN_OFF", 0)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinD611ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daikin D611 fan entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        DaikinD611Fan(coordinator, device_id)
        for device_id, device in coordinator.data.items()
        if device.device_type in VAM_TYPES
    )


class DaikinD611Fan(DaikinD611Entity, FanEntity):
    """Daikin VAM / Mini-VAM ventilation fan."""

    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | TURN_ON_FEATURE
        | TURN_OFF_FEATURE
    )
    _attr_preset_modes = list(VAM_MODE_VALUES)

    def __init__(self, coordinator: DaikinD611Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_name = None
        self._attr_unique_id = f"{self.entity_unique_id}_fan"

    @property
    def is_on(self) -> bool:
        return self.device.status.get("switch", self.device.status.get("switches")) == 1

    @property
    def percentage(self) -> int | None:
        return AIR_FLOW_TO_PERCENT.get(self.device.status.get("air_flow"))

    @property
    def preset_mode(self) -> str | None:
        return VAM_MODES.get(self.device.status.get("mode"))

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        values: dict[str, Any] = {"switch": 1}
        if percentage is not None:
            values["air_flow"] = self._percentage_to_air_flow(percentage)
        if preset_mode in VAM_MODE_VALUES:
            values["mode"] = VAM_MODE_VALUES[preset_mode]
        await self._async_control_device(**values)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_control_device(switch=0)

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage <= 0:
            await self.async_turn_off()
            return
        await self._async_control_device(switch=1, air_flow=self._percentage_to_air_flow(percentage))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in VAM_MODE_VALUES:
            return
        await self._async_control_device(mode=VAM_MODE_VALUES[preset_mode])

    @staticmethod
    def _percentage_to_air_flow(percentage: int) -> int:
        if percentage <= 25:
            return 1
        if percentage <= 50:
            return 2
        if percentage <= 75:
            return 3
        return 4
