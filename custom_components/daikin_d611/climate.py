"""Climate entities for Daikin DTA117D611."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from .const import AIR_CON_TYPES, DOMAIN
from .coordinator import DaikinD611Coordinator
from .entity import DaikinD611Entity

MODE_TO_HVAC = {
    0: HVACMode.COOL,
    1: HVACMode.DRY,
    2: HVACMode.FAN_ONLY,
    3: HVACMode.AUTO,
    4: HVACMode.HEAT,
    5: HVACMode.DRY,
    6: HVACMode.AUTO,
    7: HVACMode.AUTO,
    8: HVACMode.HEAT,
    9: HVACMode.DRY,
}
HVAC_TO_MODE = {
    HVACMode.COOL: 0,
    HVACMode.DRY: 1,
    HVACMode.FAN_ONLY: 2,
    HVACMode.AUTO: 3,
    HVACMode.HEAT: 4,
}
FAN_MODES = {
    "最弱": 0,
    "弱": 1,
    "中": 2,
    "强": 3,
    "最强": 4,
    "自动": 5,
}


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up climate entities."""

    coordinator: DaikinD611Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DaikinD611Climate(coordinator, device_id)
        for device_id, device in coordinator.data.items()
        if device.device_type in AIR_CON_TYPES
    )


class DaikinD611Climate(DaikinD611Entity, ClimateEntity):
    """Daikin indoor unit."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 16
    _attr_max_temp = 32
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
        HVACMode.AUTO,
    ]
    _attr_fan_modes = list(FAN_MODES)

    def __init__(self, coordinator: DaikinD611Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_name = None
        self._attr_unique_id = f"{self.entity_unique_id}_climate"

    @property
    def status(self) -> dict[str, Any]:
        return self.device.status

    @property
    def hvac_mode(self) -> HVACMode:
        if self.status.get("switch", self.status.get("switches")) == 0:
            return HVACMode.OFF
        return MODE_TO_HVAC.get(self.status.get("mode"), HVACMode.AUTO)

    @property
    def target_temperature(self) -> float | None:
        return self.status.get("target_temperature", self.status.get("temp"))

    @property
    def current_temperature(self) -> float | None:
        return self.status.get("room_temperature", self.status.get("indoor_temperature"))

    @property
    def current_humidity(self) -> int | None:
        return self.status.get("humidity_percent")

    @property
    def fan_mode(self) -> str | None:
        value = self.status.get("air_flow")
        if value is None:
            value = self.status.get("volume")
        for name, number in FAN_MODES.items():
            if number == value:
                return name
        return None

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_control_device(self.device_id, switch=0)
            return
        values: dict[str, Any] = {"switch": 1}
        if hvac_mode in HVAC_TO_MODE:
            values["mode"] = HVAC_TO_MODE[hvac_mode]
        await self.coordinator.async_control_device(self.device_id, **values)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.coordinator.async_control_device(self.device_id, temperature=float(temperature))

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if fan_mode not in FAN_MODES:
            return
        await self.coordinator.async_control_device(self.device_id, air_flow=FAN_MODES[fan_mode])
