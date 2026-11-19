"""Value mappings for Daikin DTA117D611 entities."""

from __future__ import annotations

AIRCON_MODES: dict[int, str] = {
    0: "制冷",
    1: "除湿",
    2: "送风",
    3: "自动",
    4: "制热",
    5: "除湿",
    6: "自动",
    7: "自动",
    8: "制热",
    9: "除湿",
}
AIRCON_MODE_VALUES: dict[str, int] = {
    "制冷": 0,
    "除湿": 1,
    "送风": 2,
    "自动": 3,
    "制热": 4,
}

AIRCON_FAN: dict[int, str] = {
    0: "最弱",
    1: "弱",
    2: "中",
    3: "强",
    4: "最强",
    5: "自动",
}
AIRCON_FAN_VALUES: dict[str, int] = {label: code for code, label in AIRCON_FAN.items()}

VAM_MODES: dict[int, str] = {
    0: "内循环",
    1: "热交换",
    2: "自动",
    3: "防污染",
    4: "排异味",
}
VAM_MODE_VALUES: dict[str, int] = {label: code for code, label in VAM_MODES.items()}

VAM_AIR_FLOW: dict[int, str] = {1: "弱", 2: "中", 3: "强", 4: "急速"}
VAM_AIR_FLOW_VALUES: dict[str, int] = {label: code for code, label in VAM_AIR_FLOW.items()}

OUTDOOR_STATUS: dict[int, str] = {0: "未知", 1: "停机", 2: "待机", 3: "运行"}
AIR_QUALITY_STATUS: dict[int, str] = {
    0: "优",
    1: "良",
    2: "轻度",
    3: "中度",
    4: "偏高",
    5: "严重",
}

FAN_DIRECTION_VERTICAL: dict[int, str] = {
    1: "⬆️",
    2: "↗️",
    3: "➡️",
    4: "↘️",
    5: "⬇️",
    6: "🅰️",
    7: "↕️",
}
FAN_DIRECTION_VERTICAL_VALUES: dict[str, int] = {
    **{label: code for code, label in FAN_DIRECTION_VERTICAL.items()},
    "自动": 6,
    "AUTO": 6,
    "auto": 6,
    "摆动": 7,
    "上下摆动": 7,
    "SWING": 7,
    "swing": 7,
    "🔄": 7,
}
FAN_DIRECTION_VERTICAL_OPTIONS: list[str] = list(FAN_DIRECTION_VERTICAL.values())

FAN_DIRECTION_HORIZONTAL: dict[int, str] = {
    1: "⬅️",
    2: "↖️",
    3: "⬆️",
    4: "↗️",
    5: "➡️",
    6: "🅰️",
    7: "↔️",
}
FAN_DIRECTION_HORIZONTAL_VALUES: dict[str, int] = {
    **{label: code for code, label in FAN_DIRECTION_HORIZONTAL.items()},
    "自动": 6,
    "AUTO": 6,
    "auto": 6,
    "摆动": 7,
    "左右摆动": 7,
    "SWING": 7,
    "swing": 7,
    "🔄": 7,
}
FAN_DIRECTION_HORIZONTAL_OPTIONS: list[str] = list(FAN_DIRECTION_HORIZONTAL.values())
