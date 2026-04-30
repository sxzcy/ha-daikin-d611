"""Value mappings for Daikin DTA117D611 entities."""

from __future__ import annotations

AIRCON_MODES = {
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
AIRCON_MODE_VALUES = {
    "制冷": 0,
    "除湿": 1,
    "送风": 2,
    "自动": 3,
    "制热": 4,
}

AIRCON_FAN = {
    0: "最弱",
    1: "弱",
    2: "中",
    3: "强",
    4: "最强",
    5: "自动",
}
AIRCON_FAN_VALUES = {value: key for key, value in AIRCON_FAN.items()}

VAM_MODES = {
    0: "内循环",
    1: "热交换",
    2: "自动",
    3: "防污染",
    4: "排异味",
}
VAM_MODE_VALUES = {value: key for key, value in VAM_MODES.items()}

VAM_AIR_FLOW = {
    1: "弱",
    2: "中",
    3: "强",
    4: "急速",
}
VAM_AIR_FLOW_VALUES = {value: key for key, value in VAM_AIR_FLOW.items()}

OUTDOOR_STATUS = {
    0: "未知",
    1: "停机",
    2: "待机",
    3: "运行",
}

AIR_QUALITY_STATUS = {
    0: "优",
    1: "良",
    2: "轻度",
    3: "中度",
    4: "偏高",
    5: "严重",
}

