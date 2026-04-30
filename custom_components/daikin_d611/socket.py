"""DTA117D611 local socket client."""

from __future__ import annotations

import logging
import socket
import struct
import time
from typing import Any

from .codec import DaikinSocketError, decode_gateway_text, to_int
from .const import (
    DEVICE_TYPE_AIR_CON,
    DEVICE_TYPE_AIR_CON_BATHROOM,
    DEVICE_TYPE_AIR_CON_NEW,
    DEVICE_TYPE_AIR_SENSOR,
    DEVICE_TYPE_MINI_VAM,
    DEVICE_TYPE_VAM,
)
from .models import DaikinDevice, DaikinGateway

_LOGGER = logging.getLogger(__name__)


class DaikinSocketClient:
    """DTA117D611 local socket client."""

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

    DEVICE_NAMES = {
        DEVICE_TYPE_AIR_CON: "AIR_CON",
        DEVICE_TYPE_AIR_CON_NEW: "AIR_CON_NEW",
        DEVICE_TYPE_AIR_CON_BATHROOM: "AIR_CON_BATHROOM",
        DEVICE_TYPE_VAM: "VAM",
        DEVICE_TYPE_MINI_VAM: "MINI_VAM",
        DEVICE_TYPE_AIR_SENSOR: "AIR_SENSOR",
    }

    def __init__(
        self,
        gateway: DaikinGateway,
        *,
        nlc_id: str,
        timeout: float,
    ) -> None:
        self.gateway = gateway
        self.nlc_id = nlc_id
        self.timeout = timeout
        self._request_id = 0

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    @staticmethod
    def build_frame(
        *,
        request_id: int,
        cmd_type: int,
        body: bytes = b"",
        flag: int = 0,
        target: int = 0,
        device_type: int = 0,
    ) -> bytes:
        frame = bytearray()
        frame.append(0x02)
        frame.extend(b"\x00\x00")
        frame.extend((0x0D, 0x00, flag & 0xFF, 0x00))
        frame.extend(struct.pack("<I", request_id))
        frame.append(target & 0xFF)
        frame.extend(struct.pack("<I", device_type))
        frame.append(0x01)
        frame.extend(struct.pack("<H", cmd_type))
        frame.extend(body)
        frame.append(0x03)
        struct.pack_into("<H", frame, 1, len(frame) - 4)
        return bytes(frame)

    def _wrap_transfer(self, inner: bytes) -> bytes:
        return self.build_frame(
            request_id=self._next_request_id(),
            cmd_type=self.CMD_TRANSFER,
            body=struct.pack("<H", len(inner)) + inner,
        )

    def _build_login_frame(self) -> bytes:
        nlc_bytes = self.nlc_id.encode("utf-8")
        gateway_id = self.gateway.key or self.gateway.mac
        gateway_bytes = gateway_id.encode("utf-8")
        body = bytearray()
        body.append(0x02)
        body.extend(struct.pack("<H", len(nlc_bytes) + len(gateway_bytes) + 3))
        body.append(0x04 if self.gateway.gateway_type == 2 else 0x01)
        body.append(len(nlc_bytes))
        body.extend(nlc_bytes)
        body.append(len(gateway_bytes))
        body.extend(gateway_bytes)
        return self.build_frame(request_id=self._next_request_id(), cmd_type=self.CMD_LOGIN, body=bytes(body))

    def _build_room_info_frame(self) -> tuple[int, bytes]:
        cmd = self.CMD_GET_ROOM_INFO_V1 if self.gateway.terminal_type in (1, 3) else self.CMD_GET_ROOM_INFO
        request_id = self._next_request_id()
        inner = self.build_frame(request_id=request_id, cmd_type=cmd, body=b"\x01\xff\xff", flag=1)
        return request_id, self._wrap_transfer(inner)

    def _build_status_query_frame(self, device_type: int, room_id: int) -> tuple[int, int, bytes]:
        is_aircon = device_type in (DEVICE_TYPE_AIR_CON, DEVICE_TYPE_AIR_CON_NEW, DEVICE_TYPE_AIR_CON_BATHROOM)
        cmd = (
            self.CMD_AIRCON_STATUS_QUERY_V1
            if is_aircon and self.gateway.terminal_type in (1, 3)
            else self.CMD_AIRCON_STATUS_QUERY
            if is_aircon
            else self.CMD_VAM_STATUS_QUERY
        )
        if is_aircon:
            body = bytes((room_id & 0xFF, 0x00, 0xFF))
        else:
            body = bytes((room_id & 0xFF, 0x00, 0x07))
        request_id = self._next_request_id()
        inner = self.build_frame(
            request_id=request_id,
            cmd_type=cmd,
            body=body,
            target=8,
            device_type=device_type,
        )
        return request_id, cmd, self._wrap_transfer(inner)

    def _build_minivam_composite_query_frame(self, room_id: int) -> tuple[int, int, bytes]:
        request_id = self._next_request_id()
        inner = self.build_frame(
            request_id=request_id,
            cmd_type=self.CMD_MINIVAM_COMPOSITE_QUERY,
            body=bytes((room_id & 0xFF, 0x00)),
            target=8,
            device_type=DEVICE_TYPE_MINI_VAM,
        )
        return request_id, self.CMD_MINIVAM_COMPOSITE_QUERY, self._wrap_transfer(inner)

    def _build_air_sensor_query_frame(self, cmd: int) -> tuple[int, int, bytes]:
        request_id = self._next_request_id()
        inner = self.build_frame(
            request_id=request_id,
            cmd_type=cmd,
            body=b"\xff",
            target=8,
            device_type=DEVICE_TYPE_AIR_SENSOR,
        )
        return request_id, cmd, self._wrap_transfer(inner)

    def _build_control_frame(
        self,
        device_type: int,
        room_id: int,
        *,
        switch: int | None = None,
        mode: int | None = None,
        air_flow: int | None = None,
        temperature: float | None = None,
    ) -> tuple[int, int, bytes]:
        cmd = self.CMD_AIRCON_STATUS_CONTROL if device_type in (DEVICE_TYPE_AIR_CON, DEVICE_TYPE_AIR_CON_NEW, DEVICE_TYPE_AIR_CON_BATHROOM) else self.CMD_VAM_STATUS_CONTROL
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
        if temperature is not None and device_type in (DEVICE_TYPE_AIR_CON, DEVICE_TYPE_AIR_CON_NEW, DEVICE_TYPE_AIR_CON_BATHROOM):
            body.extend(struct.pack("<H", int(round(temperature * 10))))
            flag |= 16
        body[2] = flag
        request_id = self._next_request_id()
        inner = self.build_frame(
            request_id=request_id,
            cmd_type=cmd,
            body=bytes(body),
            target=8,
            device_type=device_type,
        )
        return request_id, cmd, self._wrap_transfer(inner)

    @staticmethod
    def _read_exact(sock: socket.socket, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = sock.recv(size - len(chunks))
            if not chunk:
                raise DaikinSocketError("Socket closed")
            chunks.extend(chunk)
        return bytes(chunks)

    @staticmethod
    def _is_empty_frame(frame: bytes) -> bool:
        return frame == b"\x02\x00\x00\x03"

    def _read_frame(self, sock: socket.socket) -> dict[str, Any]:
        while True:
            first = self._read_exact(sock, 1)
            if first == b"\x02":
                break
        rest = self._read_exact(sock, 2)
        length = struct.unpack("<H", rest)[0]
        tail = self._read_exact(sock, length + 1)
        frame = first + rest + tail
        if self._is_empty_frame(frame):
            return {"cmd": "HEARTBEAT", "body": b"", "frame": frame}
        if frame[-1] != 0x03:
            raise DaikinSocketError(f"Invalid frame end: {frame.hex()}")
        return self._parse_frame(frame)

    def _parse_frame(self, frame: bytes) -> dict[str, Any]:
        if self._is_empty_frame(frame):
            return {"cmd": "HEARTBEAT", "body": b"", "frame": frame}
        if len(frame) < 20:
            raise DaikinSocketError(f"Frame too short: {frame.hex()}")
        declared = struct.unpack_from("<H", frame, 1)[0]
        if declared + 4 != len(frame):
            raise DaikinSocketError(f"Frame length mismatch: {declared} vs {len(frame)}")
        header_size = frame[3]
        body_start = header_size + 6
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
        if cmd_type == self.CMD_TRANSFER:
            if len(body) < 2:
                parsed["inner"] = {"cmd": "HEARTBEAT", "body": b"", "frame": body}
                return parsed
            inner_len = struct.unpack_from("<H", body, 0)[0]
            parsed["inner"] = self._parse_frame(body[2 : 2 + inner_len])
        return parsed

    @staticmethod
    def _read_u8_text(data: bytes, pos: int) -> tuple[str, bytes, int]:
        size = data[pos]
        pos += 1
        raw = data[pos : pos + size]
        if len(raw) != size:
            raise DaikinSocketError("String out of bounds")
        return decode_gateway_text(raw), raw, pos + size

    def parse_room_info(self, message: dict[str, Any]) -> list[DaikinDevice]:
        body = message.get("body") or b""
        if len(body) < 3:
            raise DaikinSocketError(f"Room info body too short: {body.hex()}")
        pos = 0
        _response_code = struct.unpack_from("<H", body, pos)[0]
        pos += 2
        room_count = body[pos]
        pos += 1
        devices: list[DaikinDevice] = []
        for _ in range(room_count):
            room_id = struct.unpack_from("<H", body, pos)[0]
            pos += 2
            room_type = body[pos]
            pos += 1
            if room_type != 2:
                room_name, room_name_raw, pos = self._read_u8_text(body, pos)
                room_alias, room_alias_raw, pos = self._read_u8_text(body, pos)
                icon, icon_raw, pos = self._read_u8_text(body, pos)
            else:
                room_name = room_alias = icon = ""
                room_name_raw = room_alias_raw = icon_raw = b""

            if room_type != 1:
                group_count = struct.unpack_from("<H", body, pos)[0]
                pos += 2
                for _group_index in range(group_count):
                    device_type = struct.unpack_from("<i", body, pos)[0]
                    pos += 4
                    device_count = struct.unpack_from("<H", body, pos)[0]
                    pos += 2
                    for unit in range(device_count):
                        device_name, device_name_raw, pos = self._read_u8_text(body, pos)
                        device_alias, device_alias_raw, pos = self._read_u8_text(body, pos)
                        devices.append(
                            DaikinDevice(
                                gateway_id=self.gateway.id,
                                gateway_name=self.gateway.name,
                                room_id=room_id,
                                room_name=room_name,
                                room_alias=room_alias,
                                device_type=device_type,
                                device_type_name=self.DEVICE_NAMES.get(device_type, str(device_type)),
                                unit=unit,
                                name=device_name,
                                alias=device_alias,
                                raw={
                                    "room_type": room_type,
                                    "icon": icon,
                                    "room_name_raw": room_name_raw.hex(),
                                    "room_alias_raw": room_alias_raw.hex(),
                                    "icon_raw": icon_raw.hex(),
                                    "device_name_raw": device_name_raw.hex(),
                                    "device_alias_raw": device_alias_raw.hex(),
                                },
                            )
                        )
        return devices

    @staticmethod
    def parse_aircon_status(body: bytes) -> dict[str, Any]:
        pos = 0
        status: dict[str, Any] = {}
        status["room_id"] = body[pos]
        pos += 1
        status["unit"] = body[pos]
        pos += 1
        flag = body[pos]
        pos += 1
        status["raw_flag"] = flag
        if flag & 1:
            status["switch"] = body[pos]
            pos += 1
        if flag >> 1 & 1:
            status["mode"] = body[pos]
            pos += 1
        if flag >> 2 & 1:
            status["air_flow"] = body[pos]
            pos += 1
        if flag >> 3 & 1:
            status["fresh_air_humidification"] = body[pos]
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
        status["raw"] = body.hex()
        return status

    @staticmethod
    def parse_vam_status(body: bytes) -> dict[str, Any]:
        pos = 0
        status: dict[str, Any] = {}
        status["room_id"] = body[pos]
        pos += 1
        status["reserved"] = body[pos]
        pos += 1
        flag = body[pos]
        pos += 1
        status["raw_flag"] = flag
        if flag & 1:
            status["switch"] = body[pos]
            pos += 1
        if flag >> 1 & 1:
            status["mode"] = body[pos]
            pos += 1
        if flag >> 2 & 1:
            status["air_flow"] = body[pos]
            pos += 1
        status["raw"] = body.hex()
        return status

    @staticmethod
    def parse_minivam_composite_status(body: bytes) -> dict[str, Any]:
        status: dict[str, Any] = {"composite_raw": body.hex()}
        if len(body) < 9:
            status["composite_parse_error"] = "short_body"
            return status

        pos = 0
        status["composite_room_id"] = body[pos]
        pos += 1
        status["composite_reserved"] = body[pos]
        pos += 1
        status["composite_serial"] = body[pos : pos + 4].hex()
        pos += 4
        status["composite_status_1"] = body[pos]
        pos += 1
        status["composite_status_2"] = body[pos]
        pos += 1
        status["composite_type"] = body[pos]
        pos += 1

        tags: dict[str, int | str] = {}
        while pos < len(body):
            tag = body[pos]
            pos += 1
            if tag == 0:
                break
            if pos >= len(body):
                status["composite_parse_error"] = "missing_tag_size"
                break

            size = body[pos]
            pos += 1
            data = body[pos : pos + size]
            if len(data) != size:
                status["composite_parse_error"] = "truncated_tag"
                break
            pos += size

            if size == 1:
                value: int | str = data[0]
            elif size == 2:
                value = struct.unpack_from("<H", data)[0]
            else:
                value = data.hex()

            tags[str(tag)] = value
            status[f"composite_tag_{tag}"] = value
            if isinstance(value, int) and tag in (2, 3, 5):
                status[f"composite_tag_{tag}_scaled"] = value / 10
            if isinstance(value, int) and tag == 5:
                status["local_temperature"] = value / 10
                status["composite_temperature"] = value / 10

        if pos < len(body):
            status["composite_sensor_count"] = body[pos]
            pos += 1
        if pos < len(body):
            status["composite_tail"] = body[pos:].hex()
        status["composite_tags"] = tags
        return status

    @staticmethod
    def _normalize_device_key(value: Any) -> str:
        return str(value or "").replace(":", "").replace("-", "").casefold()

    @staticmethod
    def _read_i16(data: bytes, pos: int) -> tuple[int, int]:
        return struct.unpack_from("<h", data, pos)[0], pos + 2

    @staticmethod
    def _nullable_scaled_short(value: int, scale: int) -> float | None:
        return None if value == 32767 else value / scale

    @classmethod
    def parse_air_sensor_info(cls, body: bytes) -> list[dict[str, Any]]:
        if len(body) < 2:
            return [{"air_sensor_info_raw": body.hex(), "air_sensor_parse_error": "short_body"}]

        pos = 0
        response_code = body[pos]
        pos += 1
        count = body[pos]
        pos += 1
        records: list[dict[str, Any]] = []
        for _index in range(count):
            record: dict[str, Any] = {
                "air_sensor_info_raw": body.hex(),
                "air_sensor_info_response": response_code,
            }
            try:
                record["room_id"] = body[pos]
                pos += 1
                record["air_sensor_packet_length"] = body[pos]
                pos += 1
                record["air_sensor_type"] = body[pos]
                pos += 1
                record["unit"] = body[pos]
                pos += 1
                record["air_sensor_mac"] = body[pos : pos + 6].hex()
                pos += 6
                alias_len = body[pos]
                pos += 1
                alias_raw = body[pos : pos + alias_len]
                pos += alias_len
                record["air_sensor_alias"] = decode_gateway_text(alias_raw)
                record["air_sensor_alias_raw"] = alias_raw.hex()
                type1 = body[pos]
                pos += 1
                type2 = body[pos]
                pos += 1
                record["air_sensor_type1"] = type1
                record["air_sensor_type2"] = type2
                record["air_sensor_connect_type"] = type2 & 1

                if type1 & 1:
                    value, pos = cls._read_i16(body, pos)
                    record["local_sensor_temperature"] = value / 10
                    record["sensor_temperature"] = value / 10
                if type1 >> 1 & 1:
                    value, pos = cls._read_i16(body, pos)
                    record["local_humidity"] = value / 10
                    record["humidity"] = value / 10
                if type1 >> 2 & 1:
                    value, pos = cls._read_i16(body, pos)
                    record["local_pm25"] = value
                    record["pm25"] = value
                if type1 >> 3 & 1:
                    value, pos = cls._read_i16(body, pos)
                    record["local_co2"] = value
                    record["co2"] = value
                if type1 >> 4 & 1:
                    record["local_voc"] = body[pos]
                    record["voc"] = body[pos]
                    pos += 1
                if type1 >> 5 & 1:
                    value, pos = cls._read_i16(body, pos)
                    record["local_tvoc"] = value / 100
                    record["tvoc"] = value / 100
                if type1 >> 6 & 1:
                    value, pos = cls._read_i16(body, pos)
                    record["local_hcho"] = value / 100
                    record["hcho"] = value / 100

                if pos < len(body):
                    record["air_sensor_alarm_switch"] = body[pos]
                    pos += 1
                limit_fields = (
                    ("temperature_upper", 10),
                    ("temperature_lower", 10),
                    ("humidity_upper", 10),
                    ("humidity_lower", 10),
                    ("pm25_upper", 1),
                    ("pm25_lower", 1),
                    ("co2_upper", 1),
                    ("co2_lower", 1),
                )
                for key, scale in limit_fields:
                    if pos + 2 > len(body):
                        break
                    value, pos = cls._read_i16(body, pos)
                    record[f"air_sensor_{key}"] = cls._nullable_scaled_short(value, scale)
                if pos < len(body):
                    record["air_sensor_voc_limit"] = body[pos]
                    pos += 1
                if pos + 2 <= len(body):
                    value, pos = cls._read_i16(body, pos)
                    record["air_sensor_tvoc_upper"] = cls._nullable_scaled_short(value, 100)
                if pos + 2 <= len(body):
                    value, pos = cls._read_i16(body, pos)
                    record["air_sensor_hcho_upper"] = cls._nullable_scaled_short(value, 100)
                if pos < len(body):
                    record["air_sensor_connected"] = body[pos]
                    pos += 1
                if pos < len(body):
                    sleep_count = body[pos]
                    record["air_sensor_sleep_mode_count"] = sleep_count
                    pos += 1
                else:
                    sleep_count = 0
                if pos < len(body):
                    record["air_sensor_sleep_mode_enable"] = body[pos]
                    pos += 1
                sleep_ranges: list[str] = []
                for _sleep_index in range(sleep_count):
                    if pos + 4 > len(body):
                        break
                    start = body[pos] * 60 + body[pos + 1]
                    stop = body[pos + 2] * 60 + body[pos + 3]
                    pos += 4
                    sleep_ranges.append(f"{start // 60:02d}:{start % 60:02d}-{stop // 60:02d}:{stop % 60:02d}")
                if sleep_ranges:
                    record["air_sensor_sleep_ranges"] = sleep_ranges
            except (IndexError, struct.error):
                record["air_sensor_parse_error"] = "truncated_record"
            records.append(record)
        return records

    @staticmethod
    def _parse_air_sensor_tlv(data: bytes) -> dict[str, int | str]:
        pos = 0
        tags: dict[str, int | str] = {}
        while pos < len(data):
            tag = data[pos]
            pos += 1
            if tag == 0:
                break
            if pos >= len(data):
                tags[str(tag)] = "missing_size"
                break
            size = data[pos]
            pos += 1
            value_data = data[pos : pos + size]
            if len(value_data) != size:
                tags[str(tag)] = "truncated"
                break
            pos += size
            if size == 1:
                value: int | str = value_data[0]
            elif size == 2:
                value = struct.unpack_from("<H", value_data)[0]
            else:
                value = value_data.hex()
            tags[str(tag)] = value
        return tags

    @classmethod
    def parse_air_sensor_status(cls, body: bytes) -> list[dict[str, Any]]:
        if not body:
            return [{"air_sensor_status_raw": body.hex(), "air_sensor_status_parse_error": "short_body"}]

        pos = 0
        count = body[pos]
        pos += 1
        records: list[dict[str, Any]] = []
        for _index in range(count):
            record: dict[str, Any] = {"air_sensor_status_raw": body.hex()}
            try:
                record["air_sensor_status_prefix1"] = body[pos]
                pos += 1
                record["air_sensor_status_prefix2"] = body[pos]
                pos += 1
                record["air_sensor_mac"] = body[pos : pos + 6].hex()
                pos += 6
                top_tags: dict[str, dict[str, int | str] | str] = {}
                while pos < len(body):
                    tag = body[pos]
                    pos += 1
                    if tag == 0:
                        break
                    if pos >= len(body):
                        top_tags[str(tag)] = "missing_size"
                        break
                    size = body[pos]
                    pos += 1
                    data = body[pos : pos + size]
                    if len(data) != size:
                        top_tags[str(tag)] = "truncated"
                        break
                    pos += size
                    top_tags[str(tag)] = cls._parse_air_sensor_tlv(data)
                record["air_sensor_status_tags"] = top_tags
                value_tags = top_tags.get("1")
                if isinstance(value_tags, dict):
                    if isinstance(value_tags.get("1"), int):
                        record["local_tvoc_status"] = value_tags["1"]
                        record["tvoc_status"] = value_tags["1"]
                    if isinstance(value_tags.get("2"), int):
                        record["air_sensor_status_tag_1_2"] = value_tags["2"]
                aux_tags = top_tags.get("2")
                if isinstance(aux_tags, dict) and isinstance(aux_tags.get("3"), int):
                    record["air_sensor_aux_status"] = aux_tags["3"]
            except (IndexError, struct.error):
                record["air_sensor_status_parse_error"] = "truncated_record"
            records.append(record)
        return records

    @classmethod
    def _match_air_sensor_records(cls, device: DaikinDevice, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        device_keys = {
            cls._normalize_device_key(device.name),
            cls._normalize_device_key(device.alias),
        }
        mac_matches = [
            record
            for record in records
            if (mac := cls._normalize_device_key(record.get("air_sensor_mac"))) and mac in device_keys
        ]
        if mac_matches:
            return mac_matches
        room_matches = [record for record in records if to_int(record.get("room_id")) == device.room_id]
        if room_matches:
            return room_matches
        return records if len(records) == 1 else []

    def _connect_and_login(self) -> socket.socket:
        sock = socket.create_connection((self.gateway.host, self.gateway.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        sock.sendall(self._build_login_frame())
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            message = self._read_frame(sock)
            if message.get("cmd") == "HEARTBEAT":
                continue
            if message.get("cmd") == self.CMD_LOGIN:
                body = message.get("body") or b""
                if len(body) >= 2 and body[1] == 1:
                    return sock
                raise DaikinSocketError(f"Gateway login failed: {body.hex()}")
        sock.close()
        raise DaikinSocketError("Gateway login timed out")

    def query_devices(self) -> list[DaikinDevice]:
        with self._connect_and_login() as sock:
            _request_id, frame = self._build_room_info_frame()
            sock.sendall(frame)
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                message = self._read_frame(sock)
                if message.get("cmd") == "HEARTBEAT":
                    continue
                inner = message.get("inner") if isinstance(message.get("inner"), dict) else message
                if inner.get("cmd") in (self.CMD_GET_ROOM_INFO, self.CMD_GET_ROOM_INFO_V1):
                    return self.parse_room_info(inner)
        raise DaikinSocketError("Room info timed out")

    def query_statuses(self, devices: list[DaikinDevice]) -> dict[str, dict[str, Any]]:
        statuses: dict[str, dict[str, Any]] = {}
        with self._connect_and_login() as sock:
            pending: dict[int, DaikinDevice] = {}
            pending_cmd: dict[int, int] = {}
            for device in devices:
                if device.device_type not in {
                    DEVICE_TYPE_AIR_CON,
                    DEVICE_TYPE_AIR_CON_NEW,
                    DEVICE_TYPE_AIR_CON_BATHROOM,
                    DEVICE_TYPE_VAM,
                    DEVICE_TYPE_MINI_VAM,
                }:
                    continue
                request_id, cmd, frame = self._build_status_query_frame(device.device_type, device.room_id)
                pending[request_id] = device
                pending_cmd[request_id] = cmd
                sock.sendall(frame)

            deadline = time.monotonic() + max(self.timeout, len(pending) * 2)
            while pending and time.monotonic() < deadline:
                message = self._read_frame(sock)
                if message.get("cmd") == "HEARTBEAT":
                    continue
                inner = message.get("inner") if isinstance(message.get("inner"), dict) else message
                request_id = inner.get("request_id")
                if request_id not in pending:
                    continue
                if inner.get("cmd") != pending_cmd.get(request_id):
                    continue
                device = pending.pop(request_id)
                body = inner.get("body") or b""
                try:
                    if device.device_type in {DEVICE_TYPE_AIR_CON, DEVICE_TYPE_AIR_CON_NEW, DEVICE_TYPE_AIR_CON_BATHROOM}:
                        statuses[device.unique_id] = self.parse_aircon_status(body)
                    else:
                        statuses[device.unique_id] = self.parse_vam_status(body)
                except Exception:
                    _LOGGER.debug("Failed to parse status for %s body=%s", device.unique_id, body.hex(), exc_info=True)

            composite_pending: dict[int, DaikinDevice] = {}
            for device in devices:
                if device.device_type != DEVICE_TYPE_MINI_VAM:
                    continue
                request_id, _cmd, frame = self._build_minivam_composite_query_frame(device.room_id)
                composite_pending[request_id] = device
                sock.sendall(frame)

            composite_deadline = time.monotonic() + max(min(self.timeout, 8), len(composite_pending) * 2)
            while composite_pending and time.monotonic() < composite_deadline:
                message = self._read_frame(sock)
                if message.get("cmd") == "HEARTBEAT":
                    continue
                inner = message.get("inner") if isinstance(message.get("inner"), dict) else message
                request_id = inner.get("request_id")
                if request_id not in composite_pending:
                    continue
                if inner.get("cmd") != self.CMD_MINIVAM_COMPOSITE_QUERY:
                    continue
                device = composite_pending.pop(request_id)
                body = inner.get("body") or b""
                try:
                    statuses[device.unique_id] = {
                        **statuses.get(device.unique_id, {}),
                        **self.parse_minivam_composite_status(body),
                    }
                except Exception:
                    _LOGGER.debug("Failed to parse MINI_VAM composite status for %s body=%s", device.unique_id, body.hex(), exc_info=True)

            air_sensor_devices = [device for device in devices if device.device_type == DEVICE_TYPE_AIR_SENSOR]
            if air_sensor_devices:
                air_sensor_pending: dict[int, int] = {}
                air_sensor_records: list[dict[str, Any]] = []
                for cmd in (self.CMD_AIR_SENSOR_INFO_2, self.CMD_AIR_SENSOR_STATUS_2):
                    request_id, query_cmd, frame = self._build_air_sensor_query_frame(cmd)
                    air_sensor_pending[request_id] = query_cmd
                    sock.sendall(frame)

                air_sensor_deadline = time.monotonic() + max(min(self.timeout, 8), len(air_sensor_pending) * 2)
                while air_sensor_pending and time.monotonic() < air_sensor_deadline:
                    message = self._read_frame(sock)
                    if message.get("cmd") == "HEARTBEAT":
                        continue
                    inner = message.get("inner") if isinstance(message.get("inner"), dict) else message
                    request_id = inner.get("request_id")
                    if request_id not in air_sensor_pending:
                        continue
                    expected_cmd = air_sensor_pending.get(request_id)
                    if inner.get("cmd") != expected_cmd:
                        continue
                    air_sensor_pending.pop(request_id)
                    body = inner.get("body") or b""
                    try:
                        if expected_cmd == self.CMD_AIR_SENSOR_INFO_2:
                            air_sensor_records.extend(self.parse_air_sensor_info(body))
                        elif expected_cmd == self.CMD_AIR_SENSOR_STATUS_2:
                            air_sensor_records.extend(self.parse_air_sensor_status(body))
                    except Exception:
                        _LOGGER.debug("Failed to parse AIR_SENSOR cmd=%s body=%s", expected_cmd, body.hex(), exc_info=True)

                for device in air_sensor_devices:
                    for matched in self._match_air_sensor_records(device, air_sensor_records):
                        statuses[device.unique_id] = {
                            **statuses.get(device.unique_id, {}),
                            **matched,
                        }
        return statuses

    def control_device(
        self,
        device: DaikinDevice,
        *,
        switch: int | None = None,
        mode: int | None = None,
        air_flow: int | None = None,
        temperature: float | None = None,
        ack_timeout: float = 3,
    ) -> dict[str, Any]:
        with self._connect_and_login() as sock:
            request_id, cmd, frame = self._build_control_frame(
                device.device_type,
                device.room_id,
                switch=switch,
                mode=mode,
                air_flow=air_flow,
                temperature=temperature,
            )
            sock.sendall(frame)
            if ack_timeout <= 0:
                return {"result": "sent_no_ack_configured"}

            deadline = time.monotonic() + ack_timeout
            original_timeout = sock.gettimeout()
            sock.settimeout(min(ack_timeout, original_timeout or ack_timeout))
            try:
                while time.monotonic() < deadline:
                    try:
                        message = self._read_frame(sock)
                    except (socket.timeout, TimeoutError):
                        break
                    if message.get("cmd") == "HEARTBEAT":
                        continue
                    inner = message.get("inner") if isinstance(message.get("inner"), dict) else message
                    if inner.get("request_id") != request_id:
                        continue
                    if inner.get("cmd") != cmd:
                        continue
                    body = inner.get("body") or b""
                    return {
                        "result": "accepted",
                        "ack_cmd": cmd,
                        "ack_request_id": request_id,
                        "ack_body": body.hex(),
                    }
            finally:
                sock.settimeout(original_timeout)
            return {
                "result": "sent_ack_timeout",
                "ack_cmd": cmd,
                "ack_request_id": request_id,
            }
