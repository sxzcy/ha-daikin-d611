"""Water heater entities for Daikin DTA117D611 HD (Heat Exchanger) devices."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.water_heater import (
    STATE_HEAT_PUMP,
    STATE_OFF,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
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
    """Set up Daikin D611 HD water heater entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        DaikinD611WaterHeater(coordinator, device_id)
        for device_id, device in coordinator.data.items()
        if device.device_type in HD_TYPES
    )


class DaikinD611WaterHeater(DaikinD611Entity, WaterHeaterEntity):
    """Daikin DTA117D611 HD water heat exchanger."""

    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 25.0
    _attr_max_temp = 55.0
    _attr_target_temperature_step = 1.0
    _attr_operation_list = [STATE_HEAT_PUMP, STATE_OFF]
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE | WaterHeaterEntityFeature.OPERATION_MODE
    )

    def __init__(self, coordinator: DaikinD611Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_name = None
        self._attr_unique_id = f"{self.entity_unique_id}_water_heater"

    @property
    def native_current_temperature(self) -> float | None:
        return self.device.status.get("warm_temperature")

    @property
    def native_target_temperature(self) -> float | None:
        return self.device.status.get("warm_temperature")

    @property
    def current_operation(self) -> str | None:
        switch_val = self.device.status.get("switch")
        if switch_val is None:
            return None
        return STATE_HEAT_PUMP if switch_val == 1 else STATE_OFF

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self._async_control_device(warm_temperature=float(temperature))

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        if operation_mode == STATE_HEAT_PUMP:
            await self._async_control_device(switch=1)
        elif operation_mode == STATE_OFF:
            await self._async_control_device(switch=0)
