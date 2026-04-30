"""Sensor entities for Daikin DTA117D611."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONCENTRATION_PARTS_PER_MILLION,
    EntityCategory,
    PERCENTAGE,
    UnitOfTemperature,
)

from .api import compact_json
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
from .mappings import AIR_QUALITY_STATUS, OUTDOOR_STATUS
from .models import DaikinDevice


@dataclass(frozen=True)
class DaikinD611SensorDescription(SensorEntityDescription):
    """Description for a derived Daikin sensor."""

    value_fn: Callable[[DaikinDevice], Any] | None = None
    attr_fn: Callable[[DaikinDevice], dict[str, Any]] | None = None


def _status_value(device: DaikinDevice, *keys: str) -> Any:
    for key in keys:
        value = device.status.get(key)
        if value is not None:
            return value
    return None


def _mapped(mapping: dict[Any, str], *keys: str) -> Callable[[DaikinDevice], str | None]:
    def value(device: DaikinDevice) -> str | None:
        raw = _status_value(device, *keys)
        if raw is None:
            return None
        return mapping.get(raw, str(raw))

    return value


def _switch(device: DaikinDevice) -> str | None:
    value = _status_value(device, "switch", "switches")
    if value is None:
        return None
    return "开" if value else "关"


def _online(device: DaikinDevice) -> str | None:
    value = _status_value(device, "cloud_online")
    if value is None:
        return None
    return "在线" if value else "离线"


def _raw_status(device: DaikinDevice) -> str | None:
    if not device.status:
        return None
    return "可用"


def _raw_status_attrs(device: DaikinDevice) -> dict[str, Any]:
    physics = device.status.get("cloud_physics")
    attributes = dict(physics) if isinstance(physics, dict) else {}
    attributes["status_json"] = compact_json(device.status)
    return attributes


AIRCON_SENSORS: tuple[DaikinD611SensorDescription, ...] = (
    DaikinD611SensorDescription(
        key="target_temperature",
        name="设定温度",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _status_value(device, "target_temperature", "temp"),
    ),
    DaikinD611SensorDescription(
        key="humidity",
        name="湿度",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _status_value(device, "humidity_percent"),
    ),
    DaikinD611SensorDescription(
        key="outdoor_status",
        name="外机状态",
        icon="mdi:hvac",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_mapped(OUTDOOR_STATUS, "outdoor_status"),
    ),
    DaikinD611SensorDescription(
        key="filter_used_time",
        name="滤网使用时间",
        icon="mdi:air-filter",
        native_unit_of_measurement="h",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: _status_value(device, "filter_used_time"),
    ),
    DaikinD611SensorDescription(
        key="raw_status",
        name="原始状态",
        icon="mdi:code-json",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_raw_status,
        attr_fn=_raw_status_attrs,
    ),
)

VAM_SENSORS: tuple[DaikinD611SensorDescription, ...] = (
    DaikinD611SensorDescription(
        key="temperature",
        name="温度",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _status_value(device, "local_temperature", "temperature"),
    ),
    DaikinD611SensorDescription(
        key="filter_used_percent",
        name="滤网使用率",
        icon="mdi:air-filter",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: _status_value(device, "filter_used_percent"),
    ),
    DaikinD611SensorDescription(
        key="raw_status",
        name="原始状态",
        icon="mdi:code-json",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_raw_status,
        attr_fn=_raw_status_attrs,
    ),
)

AIR_SENSOR_SENSORS: tuple[DaikinD611SensorDescription, ...] = (
    DaikinD611SensorDescription(
        key="temperature",
        name="温度",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _status_value(device, "local_sensor_temperature", "sensor_temperature", "temp"),
    ),
    DaikinD611SensorDescription(
        key="humidity",
        name="湿度",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _status_value(device, "local_humidity", "humidity"),
    ),
    DaikinD611SensorDescription(
        key="pm25",
        name="PM2.5",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _status_value(device, "local_pm25", "pm25"),
    ),
    DaikinD611SensorDescription(
        key="co2",
        name="CO2",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _status_value(device, "local_co2", "co2"),
    ),
    DaikinD611SensorDescription(
        key="tvoc",
        name="TVOC",
        native_unit_of_measurement="mg/m³",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:air-filter",
        value_fn=lambda device: _status_value(device, "local_tvoc", "tvoc"),
    ),
    DaikinD611SensorDescription(
        key="hcho",
        name="甲醛",
        native_unit_of_measurement="mg/m³",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:molecule",
        value_fn=lambda device: _status_value(device, "local_hcho", "hcho"),
    ),
    DaikinD611SensorDescription(
        key="voc_level",
        name="VOC 等级",
        icon="mdi:air-filter",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: _status_value(device, "local_voc", "voc"),
    ),
    DaikinD611SensorDescription(
        key="tvoc_status",
        name="TVOC 状态",
        icon="mdi:air-filter",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_mapped(AIR_QUALITY_STATUS, "local_tvoc_status", "tvoc_status"),
    ),
    DaikinD611SensorDescription(
        key="hcho_status",
        name="甲醛状态",
        icon="mdi:molecule",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_mapped(AIR_QUALITY_STATUS, "hcho_status"),
    ),
    DaikinD611SensorDescription(
        key="raw_status",
        name="原始状态",
        icon="mdi:code-json",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_raw_status,
        attr_fn=_raw_status_attrs,
    ),
)

DIAGNOSTIC_SENSORS: tuple[DaikinD611SensorDescription, ...] = (
    DaikinD611SensorDescription(
        key="last_local_refresh",
        name="最后本地刷新",
        icon="mdi:lan-connect",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: _status_value(device, "last_local_refresh"),
    ),
    DaikinD611SensorDescription(
        key="last_cloud_refresh",
        name="最后云端刷新",
        icon="mdi:cloud-sync",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: _status_value(device, "last_cloud_refresh"),
    ),
    DaikinD611SensorDescription(
        key="last_control_result",
        name="最后控制结果",
        icon="mdi:remote",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: _status_value(device, "last_control_result"),
    ),
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up sensor entities."""

    coordinator: DaikinD611Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[DaikinD611Sensor] = []
    for device_id, device in coordinator.data.items():
        if device.device_type in AIR_CON_TYPES:
            descriptions = AIRCON_SENSORS
        elif device.device_type in VAM_TYPES:
            descriptions = VAM_SENSORS
        elif device.device_type in AIR_SENSOR_TYPES:
            descriptions = AIR_SENSOR_SENSORS
        else:
            continue
        if entry.options.get(CONF_ENABLE_DIAGNOSTIC_ENTITIES, DEFAULT_ENABLE_DIAGNOSTIC_ENTITIES):
            descriptions = (*descriptions, *DIAGNOSTIC_SENSORS)
        entities.extend(DaikinD611Sensor(coordinator, device_id, description) for description in descriptions)
    async_add_entities(entities)


class DaikinD611Sensor(DaikinD611Entity, SensorEntity):
    """Daikin derived state sensor."""

    entity_description: DaikinD611SensorDescription

    def __init__(
        self,
        coordinator: DaikinD611Coordinator,
        device_id: str,
        description: DaikinD611SensorDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{self.entity_unique_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        if self.entity_description.value_fn is None:
            return self.device.status.get(self.entity_description.key)
        return self.entity_description.value_fn(self.device)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = dict(super().extra_state_attributes or {})
        if self.entity_description.attr_fn is not None:
            attributes.update(self.entity_description.attr_fn(self.device))
        return attributes
