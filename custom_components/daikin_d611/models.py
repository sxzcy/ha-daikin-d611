"""Models for Daikin DTA117D611."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .const import AIR_CON_TYPES, AIR_SENSOR_TYPES, VAM_TYPES

HEX_ALIAS_RE = re.compile(r"^(?:0x)?[0-9a-f]{6,16}$", re.IGNORECASE)
STABLE_ID_RE = re.compile(r"[^0-9A-Za-z]+")


def _clean_text(value: str | None) -> str:
    return (value or "").strip()


def _is_machine_label(value: str | None) -> bool:
    text = _clean_text(value)
    if not text:
        return True
    if HEX_ALIAS_RE.fullmatch(text):
        return True
    return bool(re.fullmatch(r"\d+-\d+", text))


def _meaningful_text(*values: str | None) -> str:
    for value in values:
        text = _clean_text(value)
        if text and not _is_machine_label(text):
            return text
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _append_suffix_once(value: str, suffix: str) -> str:
    return value if value.endswith(suffix) else f"{value}{suffix}"


def _stable_identifier(value: Any) -> str:
    text = _clean_text(str(value) if value is not None else "")
    return STABLE_ID_RE.sub("_", text).strip("_").lower()


@dataclass(slots=True)
class DaikinGateway:
    """Gateway returned by Daikin cloud."""

    home_id: str
    home_name: str
    key: str
    mac: str
    name: str
    gateway_type: int | None
    terminal_type: int | None
    host: str
    port: int
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.key or self.mac or self.name


@dataclass(slots=True)
class DaikinDevice:
    """Device discovered from local gateway room info."""

    gateway_id: str
    gateway_name: str
    room_id: int
    room_name: str
    room_alias: str
    device_type: int
    device_type_name: str
    unit: int
    name: str
    alias: str
    status: dict[str, Any] = field(default_factory=dict)
    available: bool = True
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def stable_name(self) -> str:
        cloud_physics = self.status.get("cloud_physics")
        cloud_name = cloud_physics.get("name") if isinstance(cloud_physics, dict) else None
        if self.device_type in AIR_SENSOR_TYPES:
            location = _meaningful_text(self.room_alias, self.room_name, cloud_name)
            sensor_label = _meaningful_text(cloud_name, self.alias, self.name)
            if location and sensor_label and location != sensor_label:
                return f"{location} {sensor_label}"
            return location or sensor_label or f"房间 {self.room_id}"

        label = _meaningful_text(cloud_name, self.room_alias, self.alias, self.name, self.room_name)
        if not label:
            label = f"房间 {self.room_id}"
        if self.device_type in AIR_CON_TYPES:
            return _append_suffix_once(label, "空调")
        if self.device_type in VAM_TYPES:
            return label
        return label

    @property
    def unique_id(self) -> str:
        return f"{self.gateway_id}_{self.device_type}_{self.room_id}_{self.unit}"

    @property
    def stable_physical_id(self) -> str:
        cloud_physics = self.status.get("cloud_physics")
        physics = cloud_physics if isinstance(cloud_physics, dict) else {}
        candidates = (
            self.status.get("cloud_key"),
            self.status.get("air_sensor_mac"),
            self.status.get("composite_serial"),
            physics.get("serial_no"),
            physics.get("device_no"),
            physics.get("mac"),
            physics.get("terminal_mac"),
        )
        gateway = _stable_identifier(self.gateway_id)
        device_type = _stable_identifier(self.device_type_name or self.device_type)
        prefix = "_".join(part for part in (gateway, device_type) if part)
        for candidate in candidates:
            stable = _stable_identifier(candidate)
            if stable:
                return f"{prefix}_{stable}" if prefix else stable
        fallback = _stable_identifier(self.unique_id)
        return fallback or self.unique_id
