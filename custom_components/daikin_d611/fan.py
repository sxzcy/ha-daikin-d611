"""Fan entities for Daikin DTA117D611 VAM devices."""

from __future__ import annotations

from homeassistant.components.fan import FanEntity, FanEntityFeature

from .const import DOMAIN, VAM_TYPES
from .coordinator import DaikinD611Coordinator
from .entity import DaikinD611Entity

PRESET_MODES = {
    "内循环": 0,
    "热交换": 1,
    "自动": 2,
    "防污染": 3,
    "排异味": 4,
}
PRESET_TO_MODE = {value: key for key, value in PRESET_MODES.items()}
PERCENT_TO_AIR_FLOW = {
    25: 1,
    50: 2,
    75: 3,
    100: 4,
}
AIR_FLOW_TO_PERCENT = {value: key for key, value in PERCENT_TO_AIR_FLOW.items()}
TURN_ON_FEATURE = getattr(FanEntityFeature, "TURN_ON", 0)
TURN_OFF_FEATURE = getattr(FanEntityFeature, "TURN_OFF", 0)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up fan entities."""

    coordinator: DaikinD611Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DaikinD611Fan(coordinator, device_id)
        for device_id, device in coordinator.data.items()
        if device.device_type in VAM_TYPES
    )


class DaikinD611Fan(DaikinD611Entity, FanEntity):
    """Daikin VAM / Mini VAM fan."""

    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | TURN_ON_FEATURE
        | TURN_OFF_FEATURE
    )
    _attr_preset_modes = list(PRESET_MODES)

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
        return PRESET_TO_MODE.get(self.device.status.get("mode"))

    async def async_turn_on(self, percentage: int | None = None, preset_mode: str | None = None, **kwargs) -> None:
        values = {"switch": 1}
        if percentage is not None:
            values["air_flow"] = self._percentage_to_air_flow(percentage)
        if preset_mode in PRESET_MODES:
            values["mode"] = PRESET_MODES[preset_mode]
        await self.coordinator.async_control_device(self.device_id, **values)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_control_device(self.device_id, switch=0)

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage <= 0:
            await self.async_turn_off()
            return
        await self.coordinator.async_control_device(
            self.device_id,
            switch=1,
            air_flow=self._percentage_to_air_flow(percentage),
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in PRESET_MODES:
            return
        await self.coordinator.async_control_device(self.device_id, mode=PRESET_MODES[preset_mode])

    @staticmethod
    def _percentage_to_air_flow(percentage: int) -> int:
        if percentage <= 25:
            return 1
        if percentage <= 50:
            return 2
        if percentage <= 75:
            return 3
        return 4
