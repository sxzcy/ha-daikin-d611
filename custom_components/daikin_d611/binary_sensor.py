"""Binary sensor entities for Daikin DTA117D611."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory

from .const import (
    AIR_CON_TYPES,
    AIR_SENSOR_TYPES,
    CONF_ENABLE_DIAGNOSTIC_ENTITIES,
    DEFAULT_ENABLE_DIAGNOSTIC_ENTITIES,
    DOMAIN,
    VAM_TYPES,
)
from .coordinator import DaikinD611Coordinator
from .entity import DaikinD611Entity
from .models import DaikinDevice


@dataclass(frozen=True)
class DaikinD611BinarySensorDescription(BinarySensorEntityDescription):
    """Description for a derived Daikin binary sensor."""

    value_fn: Callable[[DaikinDevice], bool | None] | None = None


def _status_value(device: DaikinDevice, *keys: str) -> Any:
    for key in keys:
        value = device.status.get(key)
        if value is not None:
            return value
    return None


def _online(device: DaikinDevice) -> bool | None:
    value = _status_value(device, "cloud_online")
    if value is None:
        return None
    return bool(value)


def _power(device: DaikinDevice) -> bool | None:
    value = _status_value(device, "switch", "switches")
    if value is None:
        return None
    return bool(value)


def _above(device: DaikinDevice, key: str, threshold: float) -> bool | None:
    value = _status_value(device, key)
    if value is None:
        return None
    try:
        return float(value) > threshold
    except (TypeError, ValueError):
        return None


def _status_problem(device: DaikinDevice, key: str) -> bool | None:
    value = _status_value(device, key)
    if value is None:
        return None
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return None


COMMON_SENSORS: tuple[DaikinD611BinarySensorDescription, ...] = (
    DaikinD611BinarySensorDescription(
        key="online",
        name="在线",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_online,
    ),
)

DIAGNOSTIC_SENSORS: tuple[DaikinD611BinarySensorDescription, ...] = (
    DaikinD611BinarySensorDescription(
        key="local_gateway",
        name="本地网关",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: bool(_status_value(device, "local_gateway_available")),
    ),
    DaikinD611BinarySensorDescription(
        key="cloud_snapshot",
        name="云端快照",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: bool(_status_value(device, "cloud_snapshot_available")),
    ),
)

POWER_SENSORS: tuple[DaikinD611BinarySensorDescription, ...] = (
    DaikinD611BinarySensorDescription(
        key="power",
        name="电源",
        device_class=BinarySensorDeviceClass.POWER,
        value_fn=_power,
    ),
)

AIR_SENSOR_PROBLEM_SENSORS: tuple[DaikinD611BinarySensorDescription, ...] = (
    DaikinD611BinarySensorDescription(
        key="pm25_problem",
        name="PM2.5 超标",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: _above(device, "pm25", 75),
    ),
    DaikinD611BinarySensorDescription(
        key="co2_problem",
        name="CO2 超标",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: _above(device, "co2", 1000),
    ),
    DaikinD611BinarySensorDescription(
        key="tvoc_problem",
        name="TVOC 异常",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: _status_problem(device, "tvoc_status"),
    ),
    DaikinD611BinarySensorDescription(
        key="hcho_problem",
        name="甲醛异常",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: _status_problem(device, "hcho_status"),
    ),
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up binary sensor entities."""

    coordinator: DaikinD611Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[DaikinD611BinarySensor] = []
    for device_id, device in coordinator.data.items():
        descriptions = list(COMMON_SENSORS)
        if device.device_type in AIR_CON_TYPES or device.device_type in VAM_TYPES:
            descriptions.extend(POWER_SENSORS)
        if device.device_type in AIR_SENSOR_TYPES:
            descriptions.extend(AIR_SENSOR_PROBLEM_SENSORS)
        if entry.options.get(CONF_ENABLE_DIAGNOSTIC_ENTITIES, DEFAULT_ENABLE_DIAGNOSTIC_ENTITIES):
            descriptions.extend(DIAGNOSTIC_SENSORS)
        entities.extend(DaikinD611BinarySensor(coordinator, device_id, description) for description in descriptions)
    async_add_entities(entities)


class DaikinD611BinarySensor(DaikinD611Entity, BinarySensorEntity):
    """Daikin binary status sensor."""

    entity_description: DaikinD611BinarySensorDescription

    def __init__(
        self,
        coordinator: DaikinD611Coordinator,
        device_id: str,
        description: DaikinD611BinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{self.entity_unique_id}_{description.key}_binary"

    @property
    def is_on(self) -> bool | None:
        if self.entity_description.value_fn is None:
            return None
        return self.entity_description.value_fn(self.device)
