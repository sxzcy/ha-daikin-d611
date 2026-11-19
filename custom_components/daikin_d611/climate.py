"""Climate entities for Daikin DTA117D611 indoor AC units."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import HVACAction, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import AIR_CON_TYPES, AIR_SENSOR_TYPES, VAM_TYPES
from .coordinator import DaikinD611Coordinator
from .entity import DaikinD611Entity
from .mappings import AIRCON_FAN, AIRCON_FAN_VALUES

if TYPE_CHECKING:
    from . import DaikinD611ConfigEntry

MODE_TO_HVAC: dict[int, HVACMode] = {
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
MODE_TO_ACTION: dict[int, HVACAction] = {
    0: HVACAction.COOLING,
    1: HVACAction.DRYING,
    2: HVACAction.FAN,
    3: HVACAction.IDLE,
    4: HVACAction.HEATING,
    5: HVACAction.DRYING,
    6: HVACAction.IDLE,
    7: HVACAction.IDLE,
    8: HVACAction.HEATING,
    9: HVACAction.DRYING,
}
HVAC_TO_MODE: dict[HVACMode, int] = {
    HVACMode.COOL: 0,
    HVACMode.DRY: 1,
    HVACMode.FAN_ONLY: 2,
    HVACMode.AUTO: 3,
    HVACMode.HEAT: 4,
}
TURN_ON_FEATURE = getattr(ClimateEntityFeature, "TURN_ON", 0)
TURN_OFF_FEATURE = getattr(ClimateEntityFeature, "TURN_OFF", 0)


def _first_number(status: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = status.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinD611ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daikin D611 climate entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        DaikinD611Climate(coordinator, device_id)
        for device_id, device in coordinator.data.items()
        if device.device_type in AIR_CON_TYPES
    )


class DaikinD611Climate(DaikinD611Entity, ClimateEntity):
    """Daikin DTA117D611 indoor AC unit."""

    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 16
    _attr_max_temp = 32
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | TURN_ON_FEATURE
        | TURN_OFF_FEATURE
    )
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
        HVACMode.AUTO,
    ]
    _attr_fan_modes = list(AIRCON_FAN_VALUES)

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
    def hvac_action(self) -> HVACAction | None:
        if self.status.get("switch", self.status.get("switches")) == 0:
            return HVACAction.OFF
        return MODE_TO_ACTION.get(self.status.get("mode"))

    @property
    def native_target_temperature(self) -> float | None:
        return _first_number(self.status, "target_temperature", "temp")

    @property
    def native_current_temperature(self) -> float | None:
        return self._room_status_number(
            "room_temperature",
            "indoor_temperature",
            "current_temperature",
            "local_sensor_temperature",
            "sensor_temperature",
            "local_temperature",
            "composite_temperature",
            "temperature",
        )

    @property
    def current_humidity(self) -> int | None:
        value = self._room_status_number("humidity_percent", "local_humidity", "humidity")
        return round(value) if value is not None else None

    @property
    def fan_mode(self) -> str | None:
        value = self.status.get("air_flow")
        if value is None:
            value = self.status.get("volume")
        return AIRCON_FAN.get(value)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._async_control_device(switch=0)
            return
        values: dict[str, Any] = {"switch": 1}
        if hvac_mode in HVAC_TO_MODE:
            values["mode"] = HVAC_TO_MODE[hvac_mode]
        await self._async_control_device(**values)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_control_device(switch=1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_control_device(switch=0)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self._async_control_device(temperature=float(temperature))

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if fan_mode not in AIRCON_FAN_VALUES:
            return
        await self._async_control_device(air_flow=AIRCON_FAN_VALUES[fan_mode])

    def _room_status_number(self, *keys: str) -> float | None:
        if (value := _first_number(self.status, *keys)) is not None:
            return value
        for device in self.coordinator.data.values():
            if device.unique_id == self.device_id or device.room_id != self.device.room_id:
                continue
            if device.device_type not in AIR_SENSOR_TYPES and device.device_type not in VAM_TYPES:
                continue
            if (value := _first_number(device.status, *keys)) is not None:
                return value
        return None
