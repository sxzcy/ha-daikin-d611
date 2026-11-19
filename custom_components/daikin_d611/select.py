"""Select entities for Daikin DTA117D611."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import AIR_CON_TYPES, VAM_TYPES
from .coordinator import DaikinD611Coordinator
from .entity import DaikinD611Entity
from .mappings import (
    AIRCON_FAN,
    AIRCON_FAN_VALUES,
    AIRCON_MODES,
    AIRCON_MODE_VALUES,
    VAM_AIR_FLOW,
    VAM_AIR_FLOW_VALUES,
    VAM_MODES,
    VAM_MODE_VALUES,
)
from .models import DaikinDevice

if TYPE_CHECKING:
    from . import DaikinD611ConfigEntry


@dataclass(frozen=True, kw_only=True)
class DaikinD611SelectDescription(SelectEntityDescription):
    """Declarative description for a Daikin select entity."""

    options_map: dict[int, str]
    values_map: dict[str, int]
    control_key: str
    read_keys: tuple[str, ...]
    force_power_on: bool = True


def _status_value(device: DaikinDevice, *keys: str) -> Any:
    for key in keys:
        value = device.status.get(key)
        if value is not None:
            return value
    return None


AIRCON_SELECTS: tuple[DaikinD611SelectDescription, ...] = (
    DaikinD611SelectDescription(
        key="mode",
        name="运行模式",
        options=list(AIRCON_MODE_VALUES),
        options_map=AIRCON_MODES,
        values_map=AIRCON_MODE_VALUES,
        control_key="mode",
        read_keys=("mode",),
    ),
    DaikinD611SelectDescription(
        key="fan",
        name="风量",
        options=list(AIRCON_FAN_VALUES),
        options_map=AIRCON_FAN,
        values_map=AIRCON_FAN_VALUES,
        control_key="air_flow",
        read_keys=("air_flow", "volume"),
    ),
)

VAM_SELECTS: tuple[DaikinD611SelectDescription, ...] = (
    DaikinD611SelectDescription(
        key="mode",
        name="运行模式",
        options=list(VAM_MODE_VALUES),
        options_map=VAM_MODES,
        values_map=VAM_MODE_VALUES,
        control_key="mode",
        read_keys=("mode",),
    ),
    DaikinD611SelectDescription(
        key="air_flow",
        name="风量",
        options=list(VAM_AIR_FLOW_VALUES),
        options_map=VAM_AIR_FLOW,
        values_map=VAM_AIR_FLOW_VALUES,
        control_key="air_flow",
        read_keys=("air_flow",),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinD611ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daikin D611 select entities."""
    coordinator = entry.runtime_data
    entities: list[DaikinD611Select] = []
    for device_id, device in coordinator.data.items():
        if device.device_type in AIR_CON_TYPES:
            descriptions = AIRCON_SELECTS
        elif device.device_type in VAM_TYPES:
            descriptions = VAM_SELECTS
        else:
            continue
        entities.extend(DaikinD611Select(coordinator, device_id, desc) for desc in descriptions)
    async_add_entities(entities)


class DaikinD611Select(DaikinD611Entity, SelectEntity):
    """Daikin mode or fan-speed select entity."""

    entity_description: DaikinD611SelectDescription

    def __init__(
        self,
        coordinator: DaikinD611Coordinator,
        device_id: str,
        description: DaikinD611SelectDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{self.entity_unique_id}_{description.key}_select"

    @property
    def current_option(self) -> str | None:
        value = _status_value(self.device, *self.entity_description.read_keys)
        if value is None:
            return None
        return self.entity_description.options_map.get(value, str(value))

    async def async_select_option(self, option: str) -> None:
        if option not in self.entity_description.values_map:
            return
        values: dict[str, Any] = {self.entity_description.control_key: self.entity_description.values_map[option]}
        if self.entity_description.force_power_on:
            values["switch"] = 1
        await self._async_control_device(**values)
