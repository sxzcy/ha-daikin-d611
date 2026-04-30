"""Base entities for Daikin DTA117D611."""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_USE_STABLE_IDS, DEFAULT_USE_STABLE_IDS, DOMAIN
from .coordinator import DaikinD611Coordinator
from .models import DaikinDevice


class DaikinD611Entity(CoordinatorEntity[DaikinD611Coordinator]):
    """Base Daikin DTA117D611 entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DaikinD611Coordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        device = self.device
        self._attr_unique_id = self.entity_unique_id
        device_identifier = device.stable_physical_id if self._use_stable_ids else device.unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_identifier)},
            name=device.stable_name,
            manufacturer="Daikin",
            model=f"DTA117D611 {device.device_type_name}",
            via_device=(DOMAIN, device.gateway_id),
        )

    @property
    def device(self) -> DaikinDevice:
        return self.coordinator.data[self.device_id]

    @property
    def entity_unique_id(self) -> str:
        if self._use_stable_ids:
            return self.device.stable_physical_id
        return self.device.unique_id

    @property
    def _use_stable_ids(self) -> bool:
        return bool(self.coordinator.entry.options.get(CONF_USE_STABLE_IDS, DEFAULT_USE_STABLE_IDS))

    @property
    def available(self) -> bool:
        return super().available and self.device_id in self.coordinator.data and self.device.available

    @property
    def extra_state_attributes(self):
        device = self.device
        attributes = {
            "gateway": device.gateway_name,
            "legacy_unique_id": device.unique_id,
            "stable_physical_id": device.stable_physical_id,
            "room_id": device.room_id,
            "room_name": device.room_name,
            "room_alias": device.room_alias,
            "device_type": device.device_type,
            "device_type_name": device.device_type_name,
            "unit": device.unit,
            "raw_status": device.status.get("raw"),
        }
        for key in (
            "local_temperature",
            "composite_temperature",
            "composite_raw",
            "composite_tags",
            "air_sensor_info_raw",
            "air_sensor_status_raw",
            "air_sensor_status_tags",
            "air_sensor_mac",
            "local_sensor_temperature",
            "local_humidity",
            "local_pm25",
            "local_co2",
            "local_tvoc",
            "local_voc",
            "local_hcho",
            "local_tvoc_status",
            "local_source",
            "local_gateway",
            "last_local_refresh",
            "cloud_source",
            "last_cloud_refresh",
            "state_sources",
            "last_control_time",
            "last_control_result",
            "last_control_values",
            "last_control_ack_cmd",
            "last_control_ack_body",
            "last_control_ack_request_id",
            "local_gateway_available",
            "cloud_snapshot_available",
        ):
            if key in device.status:
                attributes[key] = device.status[key]
        return attributes
