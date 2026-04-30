"""Constants for Daikin DTA117D611."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "daikin_d611"

CONF_GATEWAY = "gateway"
CONF_TIMEOUT = "timeout"
CONF_CONTROL_ACK_TIMEOUT = "control_ack_timeout"
CONF_ENABLE_CLOUD_SNAPSHOT = "enable_cloud_snapshot"
CONF_ENABLE_DIAGNOSTIC_ENTITIES = "enable_diagnostic_entities"
CONF_STATE_PRIORITY = "state_priority"
CONF_USE_STABLE_IDS = "use_stable_ids"

DEFAULT_GATEWAY = "DTA117D611"
DEFAULT_SCAN_INTERVAL = 60
DEFAULT_TIMEOUT = 20
DEFAULT_CONTROL_ACK_TIMEOUT = 3
DEFAULT_ENABLE_CLOUD_SNAPSHOT = True
DEFAULT_ENABLE_DIAGNOSTIC_ENTITIES = True
DEFAULT_STATE_PRIORITY = "local_first"
DEFAULT_USE_STABLE_IDS = True

STATE_PRIORITY_CLOUD_FIRST = "cloud_first"
STATE_PRIORITY_LOCAL_FIRST = "local_first"

UNIQUE_ID_SUFFIXES = {
    "binary_sensor": (
        "_online_binary",
        "_power_binary",
        "_local_gateway_binary",
        "_cloud_snapshot_binary",
        "_pm25_problem_binary",
        "_co2_problem_binary",
        "_tvoc_problem_binary",
        "_hcho_problem_binary",
    ),
    "climate": ("_climate",),
    "fan": ("_fan",),
    "select": ("_mode_select", "_fan_select", "_air_flow_select"),
    "sensor": (
        "_target_temperature",
        "_humidity",
        "_outdoor_status",
        "_filter_used_time",
        "_raw_status",
        "_temperature",
        "_filter_used_percent",
        "_pm25",
        "_co2",
        "_tvoc",
        "_hcho",
        "_voc_level",
        "_tvoc_status",
        "_hcho_status",
        "_last_local_refresh",
        "_last_cloud_refresh",
        "_last_control_result",
    ),
}

DIAGNOSTIC_UNIQUE_ID_SUFFIXES = {
    "binary_sensor": ("_local_gateway_binary", "_cloud_snapshot_binary"),
    "sensor": ("_last_local_refresh", "_last_cloud_refresh", "_last_control_result"),
}

PLATFORMS = ["climate", "fan", "sensor", "binary_sensor", "select"]

DEFAULT_UPDATE_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

DEVICE_TYPE_AIR_CON = 18
DEVICE_TYPE_AIR_CON_NEW = 23
DEVICE_TYPE_AIR_CON_BATHROOM = 24
DEVICE_TYPE_VAM = 20
DEVICE_TYPE_MINI_VAM = 28
DEVICE_TYPE_AIR_SENSOR = 25

AIR_CON_TYPES = {
    DEVICE_TYPE_AIR_CON,
    DEVICE_TYPE_AIR_CON_NEW,
    DEVICE_TYPE_AIR_CON_BATHROOM,
}

VAM_TYPES = {
    DEVICE_TYPE_VAM,
    DEVICE_TYPE_MINI_VAM,
}

AIR_SENSOR_TYPES = {
    DEVICE_TYPE_AIR_SENSOR,
}
