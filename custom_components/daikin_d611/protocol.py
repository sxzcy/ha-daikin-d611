"""Pure binary protocol codecs for Daikin DTA117D611 (zero I/O, zero HA imports)."""

from __future__ import annotations

import struct
from typing import Any

from .codec import DaikinSocketError, decode_gateway_text, to_int
from .const import (
    AIR_CON_TYPES,
    DEVICE_TYPE_AIR_CON,
    DEVICE_TYPE_AIR_CON_BATHROOM,
    DEVICE_TYPE_AIR_CON_NEW,
    DEVICE_TYPE_AIR_SENSOR,
    DEVICE_TYPE_GEOTHERMIC,
    DEVICE_TYPE_MINI_VAM,
    DEVICE_TYPE_VAM,
)
from .models import DaikinDevice

MAX_SYNC_SCAN_BYTES = 65536
MAX_FRAME_PAYLOAD_LENGTH = 32768
MAX_FRAME_NESTING_DEPTH = 4

CMD_LOGIN = 16
CMD_GET_ROOM_INFO = 48
CMD_GET_ROOM_INFO_V1 = 304
CMD_TRANSFER = 40961
CMD_AIRCON_STATUS_QUERY = 3
CMD_AIRCON_STATUS_QUERY_V1 = 259
CMD_AIRCON_STATUS_CONTROL = 1
CMD_VAM_STATUS_QUERY = 3
CMD_VAM_STATUS_CONTROL = 1
CMD_MINIVAM_COMPOSITE_QUERY = 52
CMD_AIR_SENSOR_INFO_2 = 89
CMD_AIR_SENSOR_STATUS_2 = 91

DEVICE_NAMES: dict[int, str] = {
    DEVICE_TYPE_AIR_CON: "AIR_CON",
    DEVICE_TYPE_AIR_CON_NEW: "AIR_CON_NEW",
    DEVICE_TYPE_AIR_CON_BATHROOM: "AIR_CON_BATHROOM",
    DEVICE_TYPE_GEOTHERMIC: "GEOTHERMIC",
    DEVICE_TYPE_VAM: "VAM",
    DEVICE_TYPE_MINI_VAM: "MINI_VAM",
    DEVICE_TYPE_AIR_SENSOR: "AIR_SENSOR",
}

_AIR_SENSOR_METRICS: tuple[tuple[int, str, str, int], ...] = (
    (0, "local_sensor_temperature", "sensor_temperature", 10),
    (1, "local_humidity", "humidity", 10),
    (2, "local_pm25", "pm25", 1),
    (3, "local_co2", "co2", 1),
    (4, "local_voc", "voc", 0),  # 0 => u8 byte instead of i16
    (5, "local_tvoc", "tvoc", 100),
    (6, "local_hcho", "hcho", 100),
)

_AIR_SENSOR_LIMITS: tuple[tuple[str, int], ...] = (
    ("temperature_upper", 10), ("temperature_lower", 10),
    ("humidity_upper", 10), ("humidity_lower", 10),
    ("pm25_upper", 1), ("pm25_lower", 1),
    ("co2_upper", 1), ("co2_lower", 1),
)


def is_empty_frame(frame: bytes) -> bool:
    return frame == b"\x02\x00\x00\x03"


def build_frame(
    *,
    request_id: int,
    cmd_type: int,
    body: bytes = b"",
    flag: int = 0,
    target: int = 0,
    device_type: int = 0,
) -> bytes:
    """Build a single DTA117D611 binary protocol frame."""
    header = struct.pack(
        "<BHBBBBIBIBH",
        0x02, 16 + len(body), 0x0D, 0x00, flag & 0xFF, 0x00,
        request_id, target & 0xFF, device_type, 0x01, cmd_type,
    )
    return header + body + b"\x03"


def wrap_transfer(inner: bytes, *, request_id: int) -> bytes:
    """Wrap an inner frame inside a CMD_TRANSFER envelope."""
    return build_frame(request_id=request_id, cmd_type=CMD_TRANSFER, body=struct.pack("<H", len(inner)) + inner)


def build_login_frame(*, request_id: int, nlc_id: str, gateway_id: str, gateway_type: int | None) -> bytes:
    nlc_bytes = nlc_id.encode("utf-8")
    gw_bytes = gateway_id.encode("utf-8")
    body = (
        bytes((0x02,))
        + struct.pack("<H", len(nlc_bytes) + len(gw_bytes) + 3)
        + bytes((0x04 if gateway_type == 2 else 0x01, len(nlc_bytes)))
        + nlc_bytes
        + bytes((len(gw_bytes),))
        + gw_bytes
    )
    return build_frame(request_id=request_id, cmd_type=CMD_LOGIN, body=body)


def build_room_info_frame(*, inner_request_id: int, outer_request_id: int, terminal_type: int | None) -> tuple[int, bytes]:
    cmd = CMD_GET_ROOM_INFO_V1 if terminal_type in (1, 3) else CMD_GET_ROOM_INFO
    inner = build_frame(request_id=inner_request_id, cmd_type=cmd, body=b"\x01\xff\xff", flag=1)
    return cmd, wrap_transfer(inner, request_id=outer_request_id)


def build_status_query_frame(
    *, inner_request_id: int, outer_request_id: int, device_type: int, room_id: int, terminal_type: int | None,
) -> tuple[int, bytes]:
    is_aircon = device_type in AIR_CON_TYPES
    cmd = (CMD_AIRCON_STATUS_QUERY_V1 if terminal_type in (1, 3) else CMD_AIRCON_STATUS_QUERY) if is_aircon else CMD_VAM_STATUS_QUERY
    body = bytes((room_id & 0xFF, 0x00, 0xFF if is_aircon else 0x07))
    inner = build_frame(request_id=inner_request_id, cmd_type=cmd, body=body, target=8, device_type=device_type)
    return cmd, wrap_transfer(inner, request_id=outer_request_id)


def build_minivam_composite_query_frame(*, inner_request_id: int, outer_request_id: int, room_id: int) -> tuple[int, bytes]:
    inner = build_frame(
        request_id=inner_request_id, cmd_type=CMD_MINIVAM_COMPOSITE_QUERY,
        body=bytes((room_id & 0xFF, 0x00)), target=8, device_type=DEVICE_TYPE_MINI_VAM,
    )
    return CMD_MINIVAM_COMPOSITE_QUERY, wrap_transfer(inner, request_id=outer_request_id)


def build_air_sensor_query_frame(*, inner_request_id: int, outer_request_id: int, cmd: int) -> tuple[int, bytes]:
    inner = build_frame(
        request_id=inner_request_id, cmd_type=cmd, body=b"\xff", target=8, device_type=DEVICE_TYPE_AIR_SENSOR,
    )
    return cmd, wrap_transfer(inner, request_id=outer_request_id)


def build_control_frame(
    *,
    inner_request_id: int,
    outer_request_id: int,
    device_type: int,
    room_id: int,
    switch: int | None = None,
    mode: int | None = None,
    air_flow: int | None = None,
    temperature: float | None = None,
) -> tuple[int, bytes]:
    is_aircon = device_type in AIR_CON_TYPES
    cmd = CMD_AIRCON_STATUS_CONTROL if is_aircon else CMD_VAM_STATUS_CONTROL
    body = bytearray((room_id & 0xFF, 0x00, 0x00))
    flag = 0
    if switch is not None:
        body.append(switch & 0xFF)
        flag |= 1
    if mode is not None:
        body.append(mode & 0xFF)
        flag |= 2
    if air_flow is not None:
        body.append(air_flow & 0xFF)
        flag |= 4
    if temperature is not None and is_aircon:
        body.extend(struct.pack("<H", int(round(temperature * 10))))
        flag |= 16
    body[2] = flag
    inner = build_frame(request_id=inner_request_id, cmd_type=cmd, body=bytes(body), target=8, device_type=device_type)
    return cmd, wrap_transfer(inner, request_id=outer_request_id)


def parse_frame(frame: bytes, *, _depth: int = 0) -> dict[str, Any]:
    """Parse and validate a DTA117D611 binary frame."""
    if _depth > MAX_FRAME_NESTING_DEPTH:
        raise DaikinSocketError("Nested frame depth limit exceeded")
    if is_empty_frame(frame):
        return {"cmd": "HEARTBEAT", "body": b"", "frame": frame}
    if len(frame) < 20:
        raise DaikinSocketError(f"Frame too short: {frame.hex()}")
    if frame[0] != 0x02 or frame[-1] != 0x03:
        raise DaikinSocketError(f"Invalid frame markers: {frame.hex()}")
    declared = struct.unpack_from("<H", frame, 1)[0]
    if declared > MAX_FRAME_PAYLOAD_LENGTH:
        raise DaikinSocketError(f"Frame payload length {declared} exceeds maximum allowed ({MAX_FRAME_PAYLOAD_LENGTH})")
    if declared + 4 != len(frame):
        raise DaikinSocketError(f"Frame length mismatch: {declared} vs {len(frame)}")
    body_start = frame[3] + 6
    if body_start > len(frame) - 1:
        raise DaikinSocketError(f"Invalid frame header size: {frame[3]} for length {len(frame)}")

    cmd_type = struct.unpack_from("<H", frame, 17)[0]
    body = frame[body_start:-1]
    parsed: dict[str, Any] = {
        "request_id": struct.unpack_from("<I", frame, 7)[0],
        "target": frame[11],
        "device_type": struct.unpack_from("<I", frame, 12)[0],
        "cmd": cmd_type,
        "body": body,
        "frame": frame,
    }
    if cmd_type == CMD_TRANSFER:
        if len(body) < 2:
            parsed["inner"] = {"cmd": "HEARTBEAT", "body": b"", "frame": body}
            return parsed
        inner_len = struct.unpack_from("<H", body, 0)[0]
        if inner_len > len(body) - 2:
            raise DaikinSocketError(f"Inner frame length mismatch: {inner_len} vs {len(body) - 2}")
        parsed["inner"] = parse_frame(body[2 : 2 + inner_len], _depth=_depth + 1)
    return parsed


def _read_u8_text(data: bytes, pos: int) -> tuple[str, bytes, int]:
    size = data[pos]
    raw = data[pos + 1 : pos + 1 + size]
    if len(raw) != size:
        raise DaikinSocketError("String out of bounds")
    return decode_gateway_text(raw), raw, pos + 1 + size


def _parse_room_info_body(
    body: bytes, *, gateway_id: str, gateway_name: str, always_read_device_names: bool,
) -> tuple[list[DaikinDevice], int]:
    if len(body) < 3:
        raise DaikinSocketError(f"Room info body too short: {body.hex()}")
    pos = 3
    devices: list[DaikinDevice] = []
    for _ in range(body[2]):
        room_id, version_flag = struct.unpack_from("<HB", body, pos)
        pos += 3
        if version_flag != 2:
            room_name, room_name_raw, pos = _read_u8_text(body, pos)
            room_alias, room_alias_raw, pos = _read_u8_text(body, pos)
            icon, icon_raw, pos = _read_u8_text(body, pos)
        else:
            room_name = room_alias = icon = ""
            room_name_raw = room_alias_raw = icon_raw = b""
        group_count = struct.unpack_from("<H", body, pos)[0]
        pos += 2
        for _ in range(group_count):
            device_type, device_count = struct.unpack_from("<iH", body, pos)
            pos += 6
            for unit in range(device_count):
                if always_read_device_names or version_flag > 2:
                    device_name, device_name_raw, pos = _read_u8_text(body, pos)
                    device_alias, device_alias_raw, pos = _read_u8_text(body, pos)
                else:
                    device_name, device_alias = "", room_alias
                    device_name_raw = device_alias_raw = b""
                devices.append(
                    DaikinDevice(
                        gateway_id=gateway_id, gateway_name=gateway_name,
                        room_id=room_id, room_name=room_name, room_alias=room_alias,
                        device_type=device_type, device_type_name=DEVICE_NAMES.get(device_type, str(device_type)),
                        unit=unit, name=device_name, alias=device_alias,
                        raw={
                            "room_version_flag": version_flag, "icon": icon,
                            "room_name_raw": room_name_raw.hex(), "room_alias_raw": room_alias_raw.hex(),
                            "icon_raw": icon_raw.hex(), "device_name_raw": device_name_raw.hex(),
                            "device_alias_raw": device_alias_raw.hex(),
                        },
                    )
                )
    return devices, pos


def parse_room_info(body: bytes, *, gateway_id: str, gateway_name: str) -> list[DaikinDevice]:
    """Parse room & device inventory from a room-info response body."""
    errors: list[Exception] = []
    for always_read in (False, True):
        try:
            devices, pos = _parse_room_info_body(
                body, gateway_id=gateway_id, gateway_name=gateway_name, always_read_device_names=always_read,
            )
        except (IndexError, struct.error, DaikinSocketError) as exc:
            errors.append(exc)
            continue
        if pos == len(body):
            return devices
        errors.append(DaikinSocketError(f"Room info parser stopped at {pos}/{len(body)}"))
    raise DaikinSocketError(f"Could not parse room info: {errors[-1] if errors else body.hex()}")


def parse_aircon_status(body: bytes) -> dict[str, Any]:
    """Parse indoor AC status response body."""
    if len(body) < 3:
        raise DaikinSocketError(f"Aircon status body too short: {body.hex()}")
    pos, flag = 3, body[2]
    status: dict[str, Any] = {"room_id": body[0], "unit": body[1], "raw_flag": flag}
    try:
        for bit, key in ((0, "switch"), (1, "mode"), (2, "air_flow"), (3, "fresh_air_humidification")):
            if flag >> bit & 1:
                status[key] = body[pos]
                pos += 1
        if flag >> 4 & 1:
            status["target_temperature"] = struct.unpack_from("<H", body, pos)[0] / 10
            pos += 2
        if flag >> 5 & 1:
            direction = body[pos]
            pos += 1
            status["fan_direction1"] = direction & 0x0F
            status["fan_direction2"] = (direction >> 4) & 0x0F
        if flag >> 6 & 1:
            status["humidity"] = body[pos]
            pos += 1
            if pos < len(body):
                status["humidity_percent"] = body[pos]
                pos += 1
        if flag >> 7 & 1:
            status["breathe"] = body[pos]
            pos += 1
            if pos < len(body):
                status["extra_7"] = body[pos]
                pos += 1
    except (IndexError, struct.error) as exc:
        raise DaikinSocketError(f"Truncated aircon status body: {body.hex()}") from exc
    status["raw"] = body.hex()
    return status


def parse_vam_status(body: bytes) -> dict[str, Any]:
    """Parse VAM / Mini-VAM basic status response body."""
    if len(body) < 3:
        raise DaikinSocketError(f"VAM status body too short: {body.hex()}")
    pos, flag = 3, body[2]
    status: dict[str, Any] = {"room_id": body[0], "reserved": body[1], "raw_flag": flag}
    try:
        for bit, key in ((0, "switch"), (1, "mode"), (2, "air_flow")):
            if flag >> bit & 1:
                status[key] = body[pos]
                pos += 1
    except IndexError as exc:
        raise DaikinSocketError(f"Truncated VAM status body: {body.hex()}") from exc
    status["raw"] = body.hex()
    return status


def _decode_tlv_value(data: bytes) -> int | str:
    if len(data) == 1:
        return data[0]
    if len(data) == 2:
        return struct.unpack_from("<H", data)[0]
    return data.hex()


def _parse_tlv_stream(data: bytes, pos: int = 0) -> tuple[list[tuple[int, bytes]], int, tuple[int, str] | None]:
    items: list[tuple[int, bytes]] = []
    error: tuple[int, str] | None = None
    while pos < len(data):
        tag = data[pos]
        pos += 1
        if tag == 0:
            break
        if pos >= len(data):
            error = (tag, "missing_size")
            break
        size = data[pos]
        pos += 1
        value = data[pos : pos + size]
        if len(value) != size:
            error = (tag, "truncated")
            break
        pos += size
        items.append((tag, value))
    return items, pos, error


def parse_minivam_composite_status(body: bytes) -> dict[str, Any]:
    """Parse Mini-VAM composite TLV status response body."""
    status: dict[str, Any] = {"composite_raw": body.hex()}
    if len(body) < 9:
        status["composite_parse_error"] = "short_body"
        return status

    status.update({
        "composite_room_id": body[0], "composite_reserved": body[1],
        "composite_serial": body[2:6].hex(),
        "composite_status_1": body[6], "composite_status_2": body[7], "composite_type": body[8],
    })
    items, pos, error = _parse_tlv_stream(body, 9)
    tags: dict[str, int | str] = {}
    for tag, raw in items:
        value = _decode_tlv_value(raw)
        tags[str(tag)] = value
        status[f"composite_tag_{tag}"] = value
        if isinstance(value, int) and tag in (2, 3, 5):
            status[f"composite_tag_{tag}_scaled"] = value / 10
        if isinstance(value, int) and tag == 5:
            status["local_temperature"] = status["composite_temperature"] = value / 10
    if error is not None:
        status["composite_parse_error"] = "missing_tag_size" if error[1] == "missing_size" else "truncated_tag"
    if pos < len(body):
        status["composite_sensor_count"] = body[pos]
        pos += 1
    if pos < len(body):
        status["composite_tail"] = body[pos:].hex()
    status["composite_tags"] = tags
    return status


def _normalize_device_key(value: Any) -> str:
    return str(value or "").replace(":", "").replace("-", "").casefold()


def _read_i16(data: bytes, pos: int) -> tuple[int, int]:
    return struct.unpack_from("<h", data, pos)[0], pos + 2


def _nullable_scaled_short(value: int, scale: int) -> float | None:
    return None if value == 32767 else value / scale


def parse_air_sensor_info(body: bytes) -> list[dict[str, Any]]:
    """Parse Air Sensor info (cmd 89) records."""
    if len(body) < 2:
        return [{"air_sensor_info_raw": body.hex(), "air_sensor_parse_error": "short_body"}]

    response_code, count, pos = body[0], body[1], 2
    records: list[dict[str, Any]] = []
    for _ in range(count):
        record: dict[str, Any] = {"air_sensor_info_raw": body.hex(), "air_sensor_info_response": response_code}
        try:
            record.update({
                "room_id": body[pos], "air_sensor_packet_length": body[pos + 1],
                "air_sensor_type": body[pos + 2], "unit": body[pos + 3],
                "air_sensor_mac": body[pos + 4 : pos + 10].hex(),
            })
            pos += 10
            alias, alias_raw, pos = _read_u8_text(body, pos)
            type1, type2 = body[pos], body[pos + 1]
            pos += 2
            record.update({
                "air_sensor_alias": alias, "air_sensor_alias_raw": alias_raw.hex(),
                "air_sensor_type1": type1, "air_sensor_type2": type2,
                "air_sensor_connect_type": type2 & 1,
            })
            for bit, local_key, key, scale in _AIR_SENSOR_METRICS:
                if not (type1 >> bit & 1):
                    continue
                if scale == 0:
                    val: int | float = body[pos]
                    pos += 1
                else:
                    raw_i16, pos = _read_i16(body, pos)
                    val = raw_i16 if scale == 1 else raw_i16 / scale
                record[local_key] = record[key] = val

            if pos < len(body):
                record["air_sensor_alarm_switch"] = body[pos]
                pos += 1
            for name, scale in _AIR_SENSOR_LIMITS:
                if pos + 2 > len(body):
                    break
                raw_i16, pos = _read_i16(body, pos)
                record[f"air_sensor_{name}"] = _nullable_scaled_short(raw_i16, scale)
            if pos < len(body):
                record["air_sensor_voc_limit"] = body[pos]
                pos += 1
            for name in ("tvoc_upper", "hcho_upper"):
                if pos + 2 <= len(body):
                    raw_i16, pos = _read_i16(body, pos)
                    record[f"air_sensor_{name}"] = _nullable_scaled_short(raw_i16, 100)
            if pos < len(body):
                record["air_sensor_connected"] = body[pos]
                pos += 1
            sleep_count = 0
            if pos < len(body):
                sleep_count = record["air_sensor_sleep_mode_count"] = body[pos]
                pos += 1
            if pos < len(body):
                record["air_sensor_sleep_mode_enable"] = body[pos]
                pos += 1
            sleep_ranges: list[str] = []
            for _ in range(sleep_count):
                if pos + 4 > len(body):
                    break
                s, e = body[pos] * 60 + body[pos + 1], body[pos + 2] * 60 + body[pos + 3]
                pos += 4
                sleep_ranges.append(f"{s // 60:02d}:{s % 60:02d}-{e // 60:02d}:{e % 60:02d}")
            if sleep_ranges:
                record["air_sensor_sleep_ranges"] = sleep_ranges
        except (IndexError, struct.error, DaikinSocketError):
            record["air_sensor_parse_error"] = "truncated_record"
        records.append(record)
    return records


def _parse_air_sensor_tlv(data: bytes) -> dict[str, int | str]:
    items, _pos, error = _parse_tlv_stream(data)
    tags: dict[str, int | str] = {str(tag): _decode_tlv_value(raw) for tag, raw in items}
    if error is not None:
        tags[str(error[0])] = error[1]
    return tags


def parse_air_sensor_status(body: bytes) -> list[dict[str, Any]]:
    """Parse Air Sensor status (cmd 91) records."""
    if not body:
        return [{"air_sensor_status_raw": body.hex(), "air_sensor_status_parse_error": "short_body"}]

    count, pos = body[0], 1
    records: list[dict[str, Any]] = []
    for _ in range(count):
        record: dict[str, Any] = {"air_sensor_status_raw": body.hex()}
        try:
            mac_raw = body[pos + 2 : pos + 8]
            if len(mac_raw) != 6:
                raise IndexError("truncated mac")
            record.update({
                "air_sensor_status_prefix1": body[pos],
                "air_sensor_status_prefix2": body[pos + 1],
                "air_sensor_mac": mac_raw.hex(),
            })
            items, pos, error = _parse_tlv_stream(body, pos + 8)
            top_tags: dict[str, dict[str, int | str] | str] = {
                str(tag): _parse_air_sensor_tlv(raw) for tag, raw in items
            }
            if error is not None:
                top_tags[str(error[0])] = error[1]
            record["air_sensor_status_tags"] = top_tags
            value_tags = top_tags.get("1")
            if isinstance(value_tags, dict):
                if isinstance(value_tags.get("1"), int):
                    record["local_tvoc_status"] = record["tvoc_status"] = value_tags["1"]
                if isinstance(value_tags.get("2"), int):
                    record["air_sensor_status_tag_1_2"] = value_tags["2"]
            aux_tags = top_tags.get("2")
            if isinstance(aux_tags, dict) and isinstance(aux_tags.get("3"), int):
                record["air_sensor_aux_status"] = aux_tags["3"]
        except (IndexError, struct.error):
            record["air_sensor_status_parse_error"] = "truncated_record"
        records.append(record)
    return records


def match_air_sensor_records(device: DaikinDevice, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Match parsed air-sensor info/status records to a discovered DaikinDevice."""
    device_keys = {_normalize_device_key(device.name), _normalize_device_key(device.alias)}
    if mac_matches := [r for r in records if (m := _normalize_device_key(r.get("air_sensor_mac"))) and m in device_keys]:
        return mac_matches
    if room_matches := [r for r in records if to_int(r.get("room_id")) == device.room_id]:
        return room_matches
    return records if len(records) == 1 else []
