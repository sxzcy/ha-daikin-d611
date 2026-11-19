"""Sensor entities for Daikin DTA117D611."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    UnitOfDensity,
    UnitOfRatio,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    AIR_CON_TYPES,
    AIR_SENSOR_TYPES,
    CONF_ENABLE_DIAGNOSTIC_ENTITIES,
    CONF_ENABLE_POWER_STATISTICS,
    DEFAULT_ENABLE_DIAGNOSTIC_ENTITIES,
    DEFAULT_ENABLE_POWER_STATISTICS,
    DEVICE_TYPE_MINI_VAM,
    DOMAIN,
    GEOTHERMIC_TYPES,
    VAM_TYPES,
)
from .coordinator import DaikinD611Coordinator
from .entity import DaikinD611Entity
from .mappings import AIR_QUALITY_STATUS, OUTDOOR_STATUS
from .models import DaikinDevice

if TYPE_CHECKING:
    from . import DaikinD611ConfigEntry


@dataclass(frozen=True, kw_only=True)
class DaikinD611SensorDescription(SensorEntityDescription):
    """Declarative description for a Daikin sensor entity."""

    value_fn: Callable[[DaikinDevice], Any]
    attr_fn: Callable[[DaikinDevice], dict[str, Any]] | None = None


def _status_value(device: DaikinDevice, *keys: str) -> Any:
    for key in keys:
        value = device.status.get(key)
        if value is not None:
            return value
    return None


def _mapped(mapping: dict[Any, str], *keys: str) -> Callable[[DaikinDevice], str | None]:
    def _value(device: DaikinDevice) -> str | None:
        raw = _status_value(device, *keys)
        return None if raw is None else mapping.get(raw, str(raw))

    return _value


def _raw_status_attrs(device: DaikinDevice) -> dict[str, Any]:
    physics = device.status.get("cloud_physics")
    attributes: dict[str, Any] = {
        "status_key_count": len(device.status),
        "status_keys": sorted(device.status),
    }
    if isinstance(physics, dict):
        attributes["cloud_physics_keys"] = sorted(physics)
    return attributes


AIRCON_SENSORS: tuple[DaikinD611SensorDescription, ...] = (
    DaikinD611SensorDescription(
        key="target_temperature",
        name="设定温度",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _status_value(d, "target_temperature", "temp"),
    ),
    DaikinD611SensorDescription(
        key="humidity",
        name="湿度",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _status_value(d, "humidity_percent"),
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
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _status_value(d, "filter_used_time"),
    ),
)

VAM_SENSORS: tuple[DaikinD611SensorDescription, ...] = (
    DaikinD611SensorDescription(
        key="temperature",
        name="温度",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _status_value(d, "local_temperature", "temperature"),
    ),
    DaikinD611SensorDescription(
        key="filter_used_percent",
        name="滤网使用率",
        icon="mdi:air-filter",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _status_value(d, "filter_used_percent"),
    ),
)

MINI_VAM_EXTRA_SENSORS: tuple[DaikinD611SensorDescription, ...] = (
    DaikinD611SensorDescription(
        key="outdoor_humidity",
        name="室外湿度",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _status_value(d, "outdoor_humidity"),
    ),
    DaikinD611SensorDescription(
        key="outdoor_pm25",
        name="室外 PM2.5",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _status_value(d, "outdoor_pm25"),
    ),
)

GEOTHERMIC_SENSORS: tuple[DaikinD611SensorDescription, ...] = (
    DaikinD611SensorDescription(
        key="target_temperature",
        name="设定温度",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _status_value(d, "target_temperature", "temp"),
    ),
)

AIR_SENSOR_SENSORS: tuple[DaikinD611SensorDescription, ...] = (
    DaikinD611SensorDescription(
        key="temperature",
        name="温度",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _status_value(d, "local_sensor_temperature", "sensor_temperature", "temp"),
    ),
    DaikinD611SensorDescription(
        key="humidity",
        name="湿度",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _status_value(d, "local_humidity", "humidity"),
    ),
    DaikinD611SensorDescription(
        key="pm25",
        name="PM2.5",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _status_value(d, "local_pm25", "pm25"),
    ),
    DaikinD611SensorDescription(
        key="co2",
        name="CO2",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _status_value(d, "local_co2", "co2"),
    ),
    DaikinD611SensorDescription(
        key="tvoc",
        name="TVOC",
        native_unit_of_measurement="mg/m³",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:air-filter",
        value_fn=lambda d: _status_value(d, "local_tvoc", "tvoc"),
    ),
    DaikinD611SensorDescription(
        key="hcho",
        name="甲醛",
        native_unit_of_measurement="mg/m³",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:molecule",
        value_fn=lambda d: _status_value(d, "local_hcho", "hcho"),
    ),
    DaikinD611SensorDescription(
        key="voc_level",
        name="VOC 等级",
        icon="mdi:air-filter",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _status_value(d, "local_voc", "voc"),
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
)

DIAGNOSTIC_SENSORS: tuple[DaikinD611SensorDescription, ...] = (
    DaikinD611SensorDescription(
        key="raw_status",
        name="原始状态",
        icon="mdi:code-json",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: "可用" if d.status else None,
        attr_fn=_raw_status_attrs,
    ),
    DaikinD611SensorDescription(
        key="last_local_refresh",
        name="最后本地刷新",
        icon="mdi:lan-connect",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _status_value(d, "last_local_refresh"),
    ),
    DaikinD611SensorDescription(
        key="last_cloud_refresh",
        name="最后云端刷新",
        icon="mdi:cloud-sync",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _status_value(d, "last_cloud_refresh"),
    ),
    DaikinD611SensorDescription(
        key="last_control_result",
        name="最后控制结果",
        icon="mdi:remote",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _status_value(d, "last_control_result"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinD611ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daikin D611 sensor entities."""
    coordinator = entry.runtime_data
    enable_diag = bool(entry.options.get(CONF_ENABLE_DIAGNOSTIC_ENTITIES, DEFAULT_ENABLE_DIAGNOSTIC_ENTITIES))
    enable_power = bool(entry.options.get(CONF_ENABLE_POWER_STATISTICS, DEFAULT_ENABLE_POWER_STATISTICS))
    entities: list[SensorEntity] = []
    for device_id, device in coordinator.data.items():
        if device.device_type in AIR_CON_TYPES:
            descriptions: tuple[DaikinD611SensorDescription, ...] = AIRCON_SENSORS
        elif device.device_type in VAM_TYPES:
            descriptions = VAM_SENSORS
            if device.device_type == DEVICE_TYPE_MINI_VAM:
                descriptions = (*descriptions, *MINI_VAM_EXTRA_SENSORS)
        elif device.device_type in AIR_SENSOR_TYPES:
            descriptions = AIR_SENSOR_SENSORS
        elif device.device_type in GEOTHERMIC_TYPES:
            descriptions = GEOTHERMIC_SENSORS
        else:
            continue
        if enable_diag:
            descriptions = (*descriptions, *DIAGNOSTIC_SENSORS)
        entities.extend(DaikinD611Sensor(coordinator, device_id, desc) for desc in descriptions)
    if enable_power and coordinator.gateway is not None:
        entities.append(DaikinD611YesterdayPowerSensor(coordinator))
        entities.append(DaikinD611MonthPowerSensor(coordinator))
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
        return self.entity_description.value_fn(self.device)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = dict(super().extra_state_attributes)
        if self.entity_description.attr_fn is not None:
            attributes.update(self.entity_description.attr_fn(self.device))
        return attributes


class _DaikinD611GatewayPowerSensor(CoordinatorEntity[DaikinD611Coordinator], SensorEntity):
    """Base energy sensor attached to the D611 gateway device."""

    _attr_has_entity_name = True
    _attr_device_class = getattr(SensorDeviceClass, "ENERGY", "energy")
    _attr_native_unit_of_measurement = "kWh"

    def __init__(self, coordinator: DaikinD611Coordinator) -> None:
        super().__init__(coordinator)
        gateway = coordinator.gateway
        gw_id = gateway.id if gateway is not None else coordinator.entry.entry_id
        gw_name = (gateway.name if gateway is not None else None) or "Daikin D611 Gateway"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, gw_id)},
            manufacturer="Daikin",
            name=gw_name,
            model="DTA117D611 Gateway",
        )

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.power_data)


class DaikinD611YesterdayPowerSensor(_DaikinD611GatewayPowerSensor):
    """Daikin cloud yesterday power consumption sensor (kWh)."""

    _attr_state_class = getattr(SensorStateClass, "TOTAL", "total")

    def __init__(self, coordinator: DaikinD611Coordinator) -> None:
        super().__init__(coordinator)
        gw_id = coordinator.gateway.id if coordinator.gateway is not None else coordinator.entry.entry_id
        self._attr_name = "昨日用电"
        self._attr_unique_id = f"{gw_id}_power_yesterday"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.power_data.get("yesterday_used")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.power_data
        if not data:
            return {}
        return {
            "yesterday_date": data.get("yesterday_date"),
            "month_total": data.get("total"),
            "price": data.get("price"),
            "estimated_cost": data.get("estimated_cost"),
            "last_updated": data.get("last_updated"),
        }


class DaikinD611MonthPowerSensor(_DaikinD611GatewayPowerSensor):
    """Daikin cloud current month cumulative power consumption sensor (kWh)."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: DaikinD611Coordinator) -> None:
        super().__init__(coordinator)
        gw_id = coordinator.gateway.id if coordinator.gateway is not None else coordinator.entry.entry_id
        self._attr_name = "当月累计用电"
        self._attr_unique_id = f"{gw_id}_power_month"

    async def async_added_to_hass(self) -> None:
        if hasattr(super(), "async_added_to_hass"):
            await super().async_added_to_hass()
        self.coordinator.month_statistic_id = self.entity_id
        if self.coordinator.power_data:
            try:
                await self.coordinator.async_import_month_statistics(
                    int(self.coordinator.power_data.get("year")),
                    int(self.coordinator.power_data.get("month")),
                    self.coordinator.power_data,
                    statistic_id=self.entity_id,
                )
            except Exception:
                pass

    @property
    def native_value(self) -> float | None:
        return self.coordinator.power_data.get("total")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.power_data
        if not data:
            return {}
        return {
            "year": data.get("year"),
            "month": data.get("month"),
            "price": data.get("price"),
            "estimated_cost": data.get("estimated_cost"),
            "daily_consumptions": data.get("consumptions", []),
            "last_updated": data.get("last_updated"),
        }
