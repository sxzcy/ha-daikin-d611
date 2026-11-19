"""Pure-asyncio local TCP transport for Daikin DTA117D611 gateways."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
import logging
import struct
from typing import Any

from .codec import DaikinSocketError, format_error
from .const import AIR_CON_TYPES, DEVICE_TYPE_AIR_SENSOR, DEVICE_TYPE_HD, DEVICE_TYPE_MINI_VAM, GEOTHERMIC_TYPES, HD_TYPES, VAM_TYPES
from .models import DaikinDevice, DaikinGateway
from .protocol import (
    CMD_AIR_SENSOR_INFO_2,
    CMD_AIR_SENSOR_STATUS_2,
    CMD_GET_ROOM_INFO,
    CMD_GET_ROOM_INFO_V1,
    CMD_LOGIN,
    MAX_FRAME_PAYLOAD_LENGTH,
    MAX_SYNC_SCAN_BYTES,
    build_air_sensor_query_frame,
    build_control_frame,
    build_hd_control_frame,
    build_login_frame,
    build_minivam_composite_query_frame,
    build_room_info_frame,
    build_status_query_frame,
    match_air_sensor_records,
    parse_air_sensor_info,
    parse_air_sensor_status,
    parse_aircon_status,
    parse_frame,
    parse_hd_status,
    parse_minivam_composite_status,
    parse_room_info_packet,
    parse_vam_status,
)

_LOGGER = logging.getLogger(__name__)
_CLOSE_TIMEOUT = 2.0


async def _async_close_writer(writer: asyncio.StreamWriter | None) -> None:
    if writer is None:
        return
    try:
        writer.close()
    except OSError:
        return
    try:
        await asyncio.wait_for(writer.wait_closed(), timeout=_CLOSE_TIMEOUT)
    except (OSError, TimeoutError):
        pass


async def _async_read_exact(reader: asyncio.StreamReader, size: int, timeout: float) -> bytes:
    if timeout <= 0:
        raise TimeoutError("Frame read timed out")
    try:
        return await asyncio.wait_for(reader.readexactly(size), timeout=timeout)
    except asyncio.IncompleteReadError as exc:
        raise DaikinSocketError("Socket closed") from exc


async def async_read_frame(reader: asyncio.StreamReader, timeout: float) -> dict[str, Any]:
    """Read and parse a single bounded binary frame from an asyncio StreamReader."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    if (remaining := deadline - loop.time()) <= 0:
        raise TimeoutError("Frame read timed out")
    try:
        prefix = await asyncio.wait_for(reader.readuntil(b"\x02"), timeout=remaining)
    except asyncio.LimitOverrunError as exc:
        raise DaikinSocketError(f"Exceeded max sync scan limit ({MAX_SYNC_SCAN_BYTES} bytes) without frame start") from exc
    except asyncio.IncompleteReadError as exc:
        raise DaikinSocketError("Socket closed") from exc
    if len(prefix) - 1 >= MAX_SYNC_SCAN_BYTES:
        raise DaikinSocketError(f"Exceeded max sync scan limit ({MAX_SYNC_SCAN_BYTES} bytes) without frame start")

    rest = await _async_read_exact(reader, 2, deadline - loop.time())
    length = struct.unpack("<H", rest)[0]
    if length > MAX_FRAME_PAYLOAD_LENGTH:
        raise DaikinSocketError(f"Frame payload length {length} exceeds maximum allowed ({MAX_FRAME_PAYLOAD_LENGTH})")
    tail = await _async_read_exact(reader, length + 1, deadline - loop.time())
    return parse_frame(b"\x02" + rest + tail)


class DaikinLocalTransport:
    """Async TCP client for DTA117D611 local socket gateway."""

    PHASE_READ_TIMEOUT = 2.0

    def __init__(self, gateway: DaikinGateway, *, nlc_id: str, timeout: float) -> None:
        self.gateway = gateway
        self.nlc_id = nlc_id
        self.timeout = timeout
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _async_send(self, writer: asyncio.StreamWriter, payload: bytes) -> None:
        try:
            writer.write(payload)
            await asyncio.wait_for(writer.drain(), timeout=self.timeout)
        except TimeoutError as exc:
            raise DaikinSocketError(f"Gateway write timed out ({self.gateway.host}:{self.gateway.port})") from exc
        except OSError as exc:
            raise DaikinSocketError(f"Gateway write failed ({self.gateway.host}:{self.gateway.port}): {format_error(exc)}") from exc

    @asynccontextmanager
    async def _open_session(self) -> AsyncIterator[tuple[asyncio.StreamReader, asyncio.StreamWriter]]:
        writer: asyncio.StreamWriter | None = None
        try:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.gateway.host, self.gateway.port, limit=MAX_SYNC_SCAN_BYTES),
                    timeout=self.timeout,
                )
            except TimeoutError as exc:
                raise DaikinSocketError(f"Gateway connection timed out ({self.gateway.host}:{self.gateway.port})") from exc
            except OSError as exc:
                raise DaikinSocketError(f"Gateway connection failed ({self.gateway.host}:{self.gateway.port}): {format_error(exc)}") from exc

            await self._async_send(
                writer,
                build_login_frame(
                    request_id=self._next_id(), nlc_id=self.nlc_id,
                    gateway_id=self.gateway.key or self.gateway.mac, gateway_type=self.gateway.gateway_type,
                ),
            )
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.timeout
            logged_in = False
            while (remaining := deadline - loop.time()) > 0:
                try:
                    message = await async_read_frame(reader, remaining)
                except TimeoutError:
                    break
                if message.get("cmd") == "HEARTBEAT":
                    continue
                if message.get("cmd") == CMD_LOGIN:
                    body = message.get("body") or b""
                    if len(body) >= 2 and body[1] == 1:
                        logged_in = True
                        break
                    raise DaikinSocketError(f"Gateway login failed: {body.hex()}")
            if not logged_in:
                raise DaikinSocketError("Gateway login timed out")
            yield reader, writer
        finally:
            await _async_close_writer(writer)

    async def _async_collect_phase(
        self,
        reader: asyncio.StreamReader,
        pending: dict[int, tuple[int, Any]],
        phase_budget: float,
        on_match: Callable[[Any, int, bytes], None],
    ) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + phase_budget
        while pending and (remaining := deadline - loop.time()) > 0:
            try:
                message = await async_read_frame(reader, min(self.PHASE_READ_TIMEOUT, remaining))
            except TimeoutError:
                break
            if message.get("cmd") == "HEARTBEAT":
                continue
            inner = message.get("inner") if isinstance(message.get("inner"), dict) else message
            request_id = inner.get("request_id")
            if request_id not in pending or inner.get("cmd") != pending[request_id][0]:
                continue
            expected_cmd, ctx = pending.pop(request_id)
            on_match(ctx, expected_cmd, inner.get("body") or b"")

    async def async_query_devices(self) -> list[DaikinDevice]:
        """Connect, authenticate, and retrieve room/device inventory."""
        async with self._open_session() as (reader, writer):
            _cmd, frame = build_room_info_frame(
                inner_request_id=self._next_id(), outer_request_id=self._next_id(),
                terminal_type=self.gateway.terminal_type,
            )
            await self._async_send(writer, frame)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.timeout
            collected: list[DaikinDevice] = []
            seen_keys: set[tuple[int, int, int]] = set()
            expected_total = 0
            rooms_seen = 0

            while (remaining := deadline - loop.time()) > 0:
                read_timeout = min(self.PHASE_READ_TIMEOUT, remaining) if collected else remaining
                try:
                    message = await async_read_frame(reader, read_timeout)
                except TimeoutError:
                    break
                if message.get("cmd") == "HEARTBEAT":
                    continue
                inner = message.get("inner") if isinstance(message.get("inner"), dict) else message
                if inner.get("cmd") in (CMD_GET_ROOM_INFO, CMD_GET_ROOM_INFO_V1):
                    total_rooms, frame_rooms, chunk = parse_room_info_packet(
                        inner.get("body") or b"", gateway_id=self.gateway.id, gateway_name=self.gateway.name,
                    )
                    for dev in chunk:
                        key = (dev.device_type, dev.room_id, dev.unit)
                        if key not in seen_keys:
                            seen_keys.add(key)
                            collected.append(dev)
                    expected_total = max(expected_total, total_rooms)
                    rooms_seen += frame_rooms
                    if expected_total <= 0 or frame_rooms <= 0 or rooms_seen >= expected_total:
                        return collected
            if collected:
                return collected
        raise DaikinSocketError("Room info timed out")

    async def async_query_statuses(self, devices: list[DaikinDevice]) -> dict[str, dict[str, Any]]:
        """Query local statuses for Aircon, VAM/Mini-VAM, HD, Geothermic, and AirSensor devices."""
        statuses: dict[str, dict[str, Any]] = {}
        query_types = AIR_CON_TYPES | VAM_TYPES | HD_TYPES | GEOTHERMIC_TYPES
        async with self._open_session() as (reader, writer):
            pending: dict[int, tuple[int, DaikinDevice]] = {}
            for dev in devices:
                if dev.device_type not in query_types:
                    continue
                inner_id = self._next_id()
                cmd, frame = build_status_query_frame(
                    inner_request_id=inner_id, outer_request_id=self._next_id(),
                    device_type=dev.device_type, room_id=dev.room_id,
                    terminal_type=self.gateway.terminal_type, unit=dev.unit,
                )
                pending[inner_id] = (cmd, dev)
                await self._async_send(writer, frame)

            def _on_primary(dev: DaikinDevice, cmd: int, body: bytes) -> None:
                try:
                    if dev.device_type in AIR_CON_TYPES or dev.device_type in GEOTHERMIC_TYPES:
                        statuses[dev.unique_id] = parse_aircon_status(body)
                    elif dev.device_type in HD_TYPES:
                        statuses[dev.unique_id] = parse_hd_status(body, cmd=cmd)
                    else:
                        statuses[dev.unique_id] = parse_vam_status(body)
                except Exception:
                    _LOGGER.debug("Failed to parse status for %s", dev.unique_id, exc_info=True)

            await self._async_collect_phase(reader, pending, min(max(3.0, len(pending) * 1.0), self.timeout), _on_primary)

            comp_pending: dict[int, tuple[int, DaikinDevice]] = {}
            for dev in devices:
                if dev.device_type != DEVICE_TYPE_MINI_VAM:
                    continue
                inner_id = self._next_id()
                cmd, frame = build_minivam_composite_query_frame(
                    inner_request_id=inner_id, outer_request_id=self._next_id(), room_id=dev.room_id, unit=dev.unit,
                )
                comp_pending[inner_id] = (cmd, dev)
                await self._async_send(writer, frame)

            if comp_pending:
                def _on_comp(dev: DaikinDevice, _cmd: int, body: bytes) -> None:
                    try:
                        statuses[dev.unique_id] = {**statuses.get(dev.unique_id, {}), **parse_minivam_composite_status(body)}
                    except Exception:
                        _LOGGER.debug("Failed to parse MINI_VAM composite for %s", dev.unique_id, exc_info=True)

                await self._async_collect_phase(
                    reader, comp_pending, min(max(1.5, len(comp_pending) * 1.0), self.timeout, 3.0), _on_comp,
                )

            air_sensors = [d for d in devices if d.device_type == DEVICE_TYPE_AIR_SENSOR]
            if air_sensors:
                sensor_pending: dict[int, tuple[int, int]] = {}
                sensor_records: list[dict[str, Any]] = []
                for qcmd in (CMD_AIR_SENSOR_INFO_2, CMD_AIR_SENSOR_STATUS_2):
                    inner_id = self._next_id()
                    cmd, frame = build_air_sensor_query_frame(inner_request_id=inner_id, outer_request_id=self._next_id(), cmd=qcmd)
                    sensor_pending[inner_id] = (cmd, qcmd)
                    await self._async_send(writer, frame)

                def _on_sensor(_ctx: int, cmd: int, body: bytes) -> None:
                    try:
                        parser = parse_air_sensor_info if cmd == CMD_AIR_SENSOR_INFO_2 else parse_air_sensor_status
                        sensor_records.extend(parser(body))
                    except Exception:
                        _LOGGER.debug("Failed to parse AIR_SENSOR cmd=%s", cmd, exc_info=True)

                await self._async_collect_phase(
                    reader, sensor_pending, min(max(1.5, len(sensor_pending) * 1.0), self.timeout, 3.0), _on_sensor,
                )
                for dev in air_sensors:
                    for matched in match_air_sensor_records(dev, sensor_records):
                        statuses[dev.unique_id] = {**statuses.get(dev.unique_id, {}), **matched}
        return statuses

    async def async_control_device(
        self,
        device: DaikinDevice,
        *,
        switch: int | None = None,
        mode: int | None = None,
        air_flow: int | None = None,
        temperature: float | None = None,
        fan_direction1: int | None = None,
        fan_direction2: int | None = None,
        breathe: int | None = None,
        mute: int | None = None,
        warm_temperature: float | None = None,
        ack_timeout: float = 3.0,
    ) -> dict[str, Any]:
        """Send a control command and optionally wait for gateway ACK."""
        async with self._open_session() as (reader, writer):
            inner_id = self._next_id()
            if device.device_type == DEVICE_TYPE_HD:
                cmd, frame = build_hd_control_frame(
                    inner_request_id=inner_id, outer_request_id=self._next_id(),
                    room_id=device.room_id, unit=device.unit,
                    switch=switch, mute=mute, warm_temperature=warm_temperature,
                )
            else:
                cmd, frame = build_control_frame(
                    inner_request_id=inner_id, outer_request_id=self._next_id(),
                    device_type=device.device_type, room_id=device.room_id, unit=device.unit,
                    switch=switch, mode=mode, air_flow=air_flow, temperature=temperature,
                    fan_direction1=fan_direction1, fan_direction2=fan_direction2, breathe=breathe,
                )
            await self._async_send(writer, frame)
            if ack_timeout <= 0:
                return {"result": "sent_no_ack_configured"}

            loop = asyncio.get_running_loop()
            deadline = loop.time() + ack_timeout
            while (remaining := deadline - loop.time()) > 0:
                try:
                    message = await async_read_frame(reader, remaining)
                except (TimeoutError, DaikinSocketError):
                    break
                if message.get("cmd") == "HEARTBEAT":
                    continue
                inner = message.get("inner") if isinstance(message.get("inner"), dict) else message
                if inner.get("request_id") == inner_id and inner.get("cmd") == cmd:
                    return {
                        "result": "accepted", "ack_cmd": cmd,
                        "ack_request_id": inner_id, "ack_body": (inner.get("body") or b"").hex(),
                    }
            return {"result": "sent_ack_timeout", "ack_cmd": cmd, "ack_request_id": inner_id}
