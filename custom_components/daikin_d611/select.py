"""Select entities for Daikin DTA117D611."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription

from .const import AIR_CON_TYPES, DOMAIN, VAM_TYPES
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


@dataclass(frozen=True)
class DaikinD611SelectDescription(SelectEntityDescription):
    """Description for a Daikin select entity."""

    options_map: dict[int, str] | None = None
    values_map: dict[str, int] | None = None
    status_key: str = ""
    control_key: str = ""
    read_keys: tuple[str, ...] = ()
    force_power_on: bool = False
    available_fn: Callable[[DaikinDevice], bool] | None = None


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
        status_key="mode",
        control_key="mode",
        read_keys=("mode",),
        force_power_on=True,
    ),
    DaikinD611SelectDescription(
        key="fan",
        name="风量",
        options=list(AIRCON_FAN_VALUES),
        options_map=AIRCON_FAN,
        values_map=AIRCON_FAN_VALUES,
        status_key="air_flow",
        control_key="air_flow",
        read_keys=("air_flow", "volume"),
        force_power_on=True,
    ),
)

VAM_SELECTS: tuple[DaikinD611SelectDescription, ...] = (
    DaikinD611SelectDescription(
        key="mode",
        name="运行模式",
        options=list(VAM_MODE_VALUES),
        options_map=VAM_MODES,
        values_map=VAM_MODE_VALUES,
        status_key="mode",
        control_key="mode",
        read_keys=("mode",),
        force_power_on=True,
    ),
    DaikinD611SelectDescription(
        key="air_flow",
        name="风量",
        options=list(VAM_AIR_FLOW_VALUES),
        options_map=VAM_AIR_FLOW,
        values_map=VAM_AIR_FLOW_VALUES,
        status_key="air_flow",
        control_key="air_flow",
        read_keys=("air_flow",),
        force_power_on=True,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up select entities."""

    coordinator: DaikinD611Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[DaikinD611Select] = []
    for device_id, device in coordinator.data.items():
        if device.device_type in AIR_CON_TYPES:
            descriptions = AIRCON_SELECTS
        elif device.device_type in VAM_TYPES:
            descriptions = VAM_SELECTS
        else:
            continue
        entities.extend(DaikinD611Select(coordinator, device_id, description) for description in descriptions)
    async_add_entities(entities)


class DaikinD611Select(DaikinD611Entity, SelectEntity):
    """Daikin mode or speed select."""

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
        if value is None or self.entity_description.options_map is None:
            return None
        return self.entity_description.options_map.get(value, str(value))

    async def async_select_option(self, option: str) -> None:
        if self.entity_description.values_map is None or option not in self.entity_description.values_map:
            return
        values: dict[str, Any] = {
            self.entity_description.control_key: self.entity_description.values_map[option],
        }
        if self.entity_description.force_power_on:
            values["switch"] = 1
        await self.coordinator.async_control_device(self.device_id, **values)
