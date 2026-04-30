"""Shared helpers and codecs for Daikin DTA117D611."""

from __future__ import annotations

import json
import uuid
from typing import Any


class DaikinError(RuntimeError):
    """Base integration error."""


class DaikinAuthError(DaikinError):
    """Authentication error."""


class DaikinApiError(DaikinError):
    """Cloud API error."""


class DaikinSocketError(DaikinError):
    """Socket gateway error."""


def make_push_id() -> str:
    return f"Android:INLS-{uuid.uuid4().hex}"


def first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def decode_gateway_text(raw: bytes) -> str:
    if not raw:
        return ""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "0x" + raw.hex()
    if "\ufffd" in text or any(ord(ch) < 32 and ch not in "\t\r\n" for ch in text):
        return "0x" + raw.hex()
    return text
