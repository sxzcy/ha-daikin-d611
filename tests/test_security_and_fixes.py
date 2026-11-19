"""Comprehensive unit & loopback integration tests for Daikin DTA117D611 v2.0.0."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import ssl
import struct
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
CUSTOM_COMPONENTS = ROOT / "custom_components"
INTEGRATION = CUSTOM_COMPONENTS / "daikin_d611"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _fixture(name: str) -> bytes:
    return bytes.fromhex((FIXTURES / name).read_text(encoding="ascii").strip())


def _build_stubs() -> dict[str, types.ModuleType]:
    """Build lightweight aiohttp, voluptuous, and Home Assistant 2026.11+ stubs."""
    stubs: dict[str, types.ModuleType] = {}

    # aiohttp stub (only when aiohttp is not installed locally)
    if "aiohttp" not in sys.modules:
        try:
            importlib.import_module("aiohttp")
        except ImportError:
            aiohttp_mod = types.ModuleType("aiohttp")

            class ClientError(Exception):
                pass

            class ClientTimeout:
                def __init__(self, total=None, connect=None, sock_connect=None, sock_read=None):
                    self.total = total

            class TCPConnector:
                def __init__(self, *, ssl=None, **kwargs):
                    self.ssl = ssl
                    self.kwargs = kwargs

            class ClientSession:
                def __init__(self, *, connector=None, timeout=None, **kwargs):
                    self.connector = connector
                    self.timeout = timeout
                    self.closed = False

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    await self.close()
                    return False

                async def close(self):
                    self.closed = True

                def post(self, *args, **kwargs):
                    raise NotImplementedError

                def get(self, *args, **kwargs):
                    raise NotImplementedError

            aiohttp_mod.ClientError = ClientError
            aiohttp_mod.ClientTimeout = ClientTimeout
            aiohttp_mod.TCPConnector = TCPConnector
            aiohttp_mod.ClientSession = ClientSession
            stubs["aiohttp"] = aiohttp_mod

    # voluptuous stub
    if "voluptuous" not in sys.modules:
        try:
            importlib.import_module("voluptuous")
        except ImportError:
            vol = types.ModuleType("voluptuous")

            class _Marker:
                def __init__(self, key, default=None):
                    self.schema = key
                    self.default = default

                def __hash__(self):
                    return hash((type(self).__name__, self.schema))

                def __eq__(self, other):
                    return type(self) is type(other) and self.schema == other.schema

            class Required(_Marker):
                pass

            class Optional(_Marker):
                pass

            class Schema:
                def __init__(self, schema):
                    self.schema = schema

                def __call__(self, value):
                    return value

            class In:
                def __init__(self, container):
                    self.container = container

            vol.Required = Required
            vol.Optional = Optional
            vol.Schema = Schema
            vol.In = In
            stubs["voluptuous"] = vol

    ha = types.ModuleType("homeassistant")
    stubs["homeassistant"] = ha

    ha_const = types.ModuleType("homeassistant.const")
    ha_const.ATTR_TEMPERATURE = "temperature"
    ha_const.CONF_HOST = "host"
    ha_const.CONF_PASSWORD = "password"
    ha_const.CONF_PORT = "port"
    ha_const.CONF_SCAN_INTERVAL = "scan_interval"
    ha_const.CONF_USERNAME = "username"
    ha_const.PERCENTAGE = "%"

    class EntityCategory:
        DIAGNOSTIC = "diagnostic"

    class UnitOfTemperature:
        CELSIUS = "°C"

    class UnitOfDensity:
        MICROGRAMS_PER_CUBIC_METER = "µg/m³"

    class UnitOfRatio:
        PARTS_PER_MILLION = "ppm"

    class UnitOfTime:
        HOURS = "h"
        MINUTES = "min"

    ha_const.EntityCategory = EntityCategory
    ha_const.UnitOfTemperature = UnitOfTemperature
    ha_const.UnitOfDensity = UnitOfDensity
    ha_const.UnitOfRatio = UnitOfRatio
    ha_const.UnitOfTime = UnitOfTime
    stubs["homeassistant.const"] = ha_const

    ha_core = types.ModuleType("homeassistant.core")

    class HomeAssistant:
        pass

    ha_core.HomeAssistant = HomeAssistant
    stubs["homeassistant.core"] = ha_core

    ha_exc = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    class ConfigEntryAuthFailed(HomeAssistantError):
        pass

    ha_exc.HomeAssistantError = HomeAssistantError
    ha_exc.ConfigEntryAuthFailed = ConfigEntryAuthFailed
    stubs["homeassistant.exceptions"] = ha_exc

    ha_def = types.ModuleType("homeassistant.data_entry_flow")
    ha_def.FlowResult = dict
    stubs["homeassistant.data_entry_flow"] = ha_def

    ha_ce = types.ModuleType("homeassistant.config_entries")

    class ConfigEntry:
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, entry_id="entry_1", data=None, options=None, title="Daikin"):
            self.entry_id = entry_id
            self.data = dict(data or {})
            self.options = dict(options or {})
            self.title = title
            self.runtime_data = None
            self.update_listeners = []
            self.reauth_started = False

        def add_update_listener(self, listener):
            self.update_listeners.append(listener)
            return lambda: None

        def async_on_unload(self, func):
            return func

        def async_start_reauth(self, hass):
            self.reauth_started = True

    class ConfigFlow:
        def __init_subclass__(cls, domain=None, **kwargs):
            super().__init_subclass__(**kwargs)
            cls.domain = domain

        def __init__(self):
            self.hass = None
            self.context = {}
            self._unique_id = None

        async def async_set_unique_id(self, unique_id):
            self._unique_id = unique_id

        def _abort_if_unique_id_configured(self):
            pass

        def async_show_form(self, *, step_id, data_schema=None, errors=None):
            return {"type": "form", "step_id": step_id, "data_schema": data_schema, "errors": errors or {}}

        def async_create_entry(self, *, title, data):
            return {"type": "create_entry", "title": title, "data": data}

        def async_abort(self, *, reason):
            return {"type": "abort", "reason": reason}

    class OptionsFlow:
        def __init__(self):
            self._ha_config_entry = None

        @property
        def config_entry(self):
            return self._ha_config_entry

        def async_show_form(self, *, step_id, data_schema=None, errors=None):
            return {"type": "form", "step_id": step_id, "data_schema": data_schema, "errors": errors or {}}

        def async_create_entry(self, *, title, data):
            return {"type": "create_entry", "title": title, "data": data}

    class OptionsFlowWithReload(OptionsFlow):
        pass

    ha_ce.ConfigEntry = ConfigEntry
    ha_ce.ConfigFlow = ConfigFlow
    ha_ce.OptionsFlow = OptionsFlow
    ha_ce.OptionsFlowWithReload = OptionsFlowWithReload
    ha.config_entries = ha_ce
    stubs["homeassistant.config_entries"] = ha_ce

    ha_helpers = types.ModuleType("homeassistant.helpers")
    stubs["homeassistant.helpers"] = ha_helpers

    ha_aiohttp = types.ModuleType("homeassistant.helpers.aiohttp_client")
    ha_aiohttp.async_get_clientsession = lambda hass: getattr(hass, "http_session", None)
    ha_helpers.aiohttp_client = ha_aiohttp
    stubs["homeassistant.helpers.aiohttp_client"] = ha_aiohttp

    ha_ep = types.ModuleType("homeassistant.helpers.entity_platform")
    ha_ep.AddEntitiesCallback = object
    stubs["homeassistant.helpers.entity_platform"] = ha_ep

    ha_dr = types.ModuleType("homeassistant.helpers.device_registry")

    class DeviceInfo(dict):
        pass

    class DeviceEntry:
        def __init__(self, id, identifiers=None):
            self.id = id
            self.identifiers = set(identifiers or set())

    class DeviceRegistry:
        pass

    ha_dr.DeviceInfo = DeviceInfo
    ha_dr.DeviceEntry = DeviceEntry
    ha_dr.DeviceRegistry = DeviceRegistry
    ha_dr.async_get = lambda hass: hass.device_registry
    ha_helpers.device_registry = ha_dr
    stubs["homeassistant.helpers.device_registry"] = ha_dr

    ha_er = types.ModuleType("homeassistant.helpers.entity_registry")
    ha_er.async_get = lambda hass: hass.entity_registry
    ha_helpers.entity_registry = ha_er
    stubs["homeassistant.helpers.entity_registry"] = ha_er

    ha_sel = types.ModuleType("homeassistant.helpers.selector")

    class TextSelectorType:
        PASSWORD = "password"

    class TextSelectorConfig(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.type = kwargs.get("type")

    class TextSelector:
        def __init__(self, config):
            self.config = config

    ha_sel.TextSelector = TextSelector
    ha_sel.TextSelectorConfig = TextSelectorConfig
    ha_sel.TextSelectorType = TextSelectorType
    stubs["homeassistant.helpers.selector"] = ha_sel

    ha_uc = types.ModuleType("homeassistant.helpers.update_coordinator")

    class UpdateFailed(Exception):
        pass

    class DataUpdateCoordinator:
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, hass, logger, *, name, update_interval=None):
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data = None
            self.last_update_success = True
            self.last_exception = None

        async def async_config_entry_first_refresh(self):
            self.data = await self._async_update_data()

        def async_set_updated_data(self, data):
            self.data = data

        async def async_request_refresh(self):
            self.data = await self._async_update_data()

        async def async_shutdown(self):
            pass

    class CoordinatorEntity:
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, coordinator):
            self.coordinator = coordinator

        @property
        def available(self) -> bool:
            return self.coordinator.last_update_success

        @property
        def device_info(self):
            return getattr(self, "_attr_device_info", None)

    ha_uc.UpdateFailed = UpdateFailed
    ha_uc.DataUpdateCoordinator = DataUpdateCoordinator
    ha_uc.CoordinatorEntity = CoordinatorEntity
    stubs["homeassistant.helpers.update_coordinator"] = ha_uc

    ha_comp = types.ModuleType("homeassistant.components")
    stubs["homeassistant.components"] = ha_comp

    # climate
    ha_climate = types.ModuleType("homeassistant.components.climate")
    ha_climate_const = types.ModuleType("homeassistant.components.climate.const")

    class ClimateEntity:
        pass

    class ClimateEntityFeature:
        TARGET_TEMPERATURE = 1
        FAN_MODE = 2
        TURN_ON = 4
        TURN_OFF = 8

    class HVACMode:
        OFF = "off"
        COOL = "cool"
        HEAT = "heat"
        DRY = "dry"
        FAN_ONLY = "fan_only"
        AUTO = "auto"

    class HVACAction:
        OFF = "off"
        COOLING = "cooling"
        HEATING = "heating"
        DRYING = "drying"
        FAN = "fan"
        IDLE = "idle"

    ha_climate.ClimateEntity = ClimateEntity
    ha_climate.ClimateEntityFeature = ClimateEntityFeature
    ha_climate_const.HVACMode = HVACMode
    ha_climate_const.HVACAction = HVACAction
    stubs["homeassistant.components.climate"] = ha_climate
    stubs["homeassistant.components.climate.const"] = ha_climate_const

    # fan
    ha_fan = types.ModuleType("homeassistant.components.fan")

    class FanEntity:
        pass

    class FanEntityFeature:
        SET_SPEED = 1
        PRESET_MODE = 2
        TURN_ON = 4
        TURN_OFF = 8

    ha_fan.FanEntity = FanEntity
    ha_fan.FanEntityFeature = FanEntityFeature
    stubs["homeassistant.components.fan"] = ha_fan

    # select
    ha_select = types.ModuleType("homeassistant.components.select")

    @dataclass(frozen=True, kw_only=True)
    class SelectEntityDescription:
        key: str = ""
        name: str | None = None
        options: list[str] | None = None

    class SelectEntity:
        pass

    ha_select.SelectEntity = SelectEntity
    ha_select.SelectEntityDescription = SelectEntityDescription
    stubs["homeassistant.components.select"] = ha_select

    # sensor
    ha_sensor = types.ModuleType("homeassistant.components.sensor")

    @dataclass(frozen=True, kw_only=True)
    class SensorEntityDescription:
        key: str = ""
        name: str | None = None
        device_class: str | None = None
        native_unit_of_measurement: str | None = None
        state_class: str | None = None
        icon: str | None = None
        entity_category: str | None = None
        entity_registry_enabled_default: bool = True

    class SensorDeviceClass:
        TEMPERATURE = "temperature"
        HUMIDITY = "humidity"
        PM25 = "pm25"
        CO2 = "co2"

    class SensorStateClass:
        MEASUREMENT = "measurement"
        TOTAL_INCREASING = "total_increasing"

    class SensorEntity:
        pass

    ha_sensor.SensorDeviceClass = SensorDeviceClass
    ha_sensor.SensorEntity = SensorEntity
    ha_sensor.SensorEntityDescription = SensorEntityDescription
    ha_sensor.SensorStateClass = SensorStateClass
    stubs["homeassistant.components.sensor"] = ha_sensor

    # binary_sensor
    ha_bs = types.ModuleType("homeassistant.components.binary_sensor")

    @dataclass(frozen=True, kw_only=True)
    class BinarySensorEntityDescription:
        key: str = ""
        name: str | None = None
        device_class: str | None = None
        entity_category: str | None = None
        entity_registry_enabled_default: bool = True

    class BinarySensorDeviceClass:
        CONNECTIVITY = "connectivity"
        POWER = "power"
        PROBLEM = "problem"

    class BinarySensorEntity:
        pass

    ha_bs.BinarySensorDeviceClass = BinarySensorDeviceClass
    ha_bs.BinarySensorEntity = BinarySensorEntity
    ha_bs.BinarySensorEntityDescription = BinarySensorEntityDescription
    stubs["homeassistant.components.binary_sensor"] = ha_bs

    # diagnostics
    ha_diag = types.ModuleType("homeassistant.components.diagnostics")

    def async_redact_data(data, to_redact):
        if isinstance(data, dict):
            return {
                k: "**REDACTED**" if k in to_redact else async_redact_data(v, to_redact)
                for k, v in data.items()
            }
        if isinstance(data, list):
            return [async_redact_data(i, to_redact) for i in data]
        return data

    ha_diag.async_redact_data = async_redact_data
    stubs["homeassistant.components.diagnostics"] = ha_diag

    cc = types.ModuleType("custom_components")
    cc.__path__ = [str(CUSTOM_COMPONENTS)]
    stubs["custom_components"] = cc
    return stubs


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def read(self) -> bytes:
        return self._body


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append(("POST", url))
        return self._responses.pop(0)

    def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        return self._responses.pop(0)

    async def close(self):
        self.closed = True


class _FakeHass:
    def __init__(self):
        self.data = {}
        self.http_session = _FakeSession([])
        self.device_registry = None
        self.entity_registry = None
        self.config_entries = MagicMock()
        self.config_entries.async_forward_entry_setups = AsyncMock()
        self.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        self.config_entries.async_reload = AsyncMock()

    def async_create_task(self, coro):
        return asyncio.create_task(coro)


class DaikinV2ArchitectureTests(unittest.TestCase):
    """End-to-end verification of the pure-asyncio Daikin D611 v2.0.0 rewrite."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._saved_modules = dict(sys.modules)
        for name, mod in _build_stubs().items():
            sys.modules[name] = mod
        for key in list(sys.modules):
            if key == "custom_components.daikin_d611" or key.startswith("custom_components.daikin_d611."):
                sys.modules.pop(key, None)

        cls.pkg = importlib.import_module("custom_components.daikin_d611")
        cls.cloud = importlib.import_module("custom_components.daikin_d611.cloud")
        cls.codec = importlib.import_module("custom_components.daikin_d611.codec")
        cls.protocol = importlib.import_module("custom_components.daikin_d611.protocol")
        cls.transport = importlib.import_module("custom_components.daikin_d611.transport")
        cls.models = importlib.import_module("custom_components.daikin_d611.models")
        cls.const = importlib.import_module("custom_components.daikin_d611.const")
        cls.coordinator_mod = importlib.import_module("custom_components.daikin_d611.coordinator")
        cls.entity_mod = importlib.import_module("custom_components.daikin_d611.entity")
        cls.climate_mod = importlib.import_module("custom_components.daikin_d611.climate")
        cls.fan_mod = importlib.import_module("custom_components.daikin_d611.fan")
        cls.select_mod = importlib.import_module("custom_components.daikin_d611.select")
        cls.sensor_mod = importlib.import_module("custom_components.daikin_d611.sensor")
        cls.binary_sensor_mod = importlib.import_module("custom_components.daikin_d611.binary_sensor")
        cls.diagnostics_mod = importlib.import_module("custom_components.daikin_d611.diagnostics")
        cls.config_flow_mod = importlib.import_module("custom_components.daikin_d611.config_flow")
        cls.ha_ce = sys.modules["homeassistant.config_entries"]
        cls.ha_exc = sys.modules["homeassistant.exceptions"]
        cls.ha_uc = sys.modules["homeassistant.helpers.update_coordinator"]
        cls.ha_dr = sys.modules["homeassistant.helpers.device_registry"]
        cls.ha_const = sys.modules["homeassistant.const"]

    @classmethod
    def tearDownClass(cls) -> None:
        for key in list(sys.modules):
            if key not in cls._saved_modules:
                sys.modules.pop(key, None)
        sys.modules.update(cls._saved_modules)

    def _make_gateway(self, host: str = "127.0.0.1", port: int = 8008):
        return self.models.DaikinGateway(
            home_id="home1", home_name="Home", key="gwkey01", mac="aabbccddeeff",
            name="DTA117D611", gateway_type=1, terminal_type=1, host=host, port=port,
            raw={"socketIp": host},
        )

    def _make_device(self, device_type: int = 18, room_id: int = 1, unit: int = 0, status: dict | None = None):
        names = {18: "AIR_CON", 20: "VAM", 28: "MINI_VAM", 25: "AIR_SENSOR"}
        return self.models.DaikinDevice(
            gateway_id="gwkey01", gateway_name="DTA117D611",
            room_id=room_id, room_name=f"Room{room_id}", room_alias=f"房间{room_id}",
            device_type=device_type, device_type_name=names[device_type],
            unit=unit, name=f"unit{room_id}_{unit}", alias=f"设备{room_id}",
            status=dict({"switch": 1, "mode": 0, "target_temperature": 24.5, "local_gateway_available": True} if status is None else status),
            available=True,
        )

    # ---- Packaging, Hygiene & Architecture ----
    def test_manifest_assets_and_zero_blocking_imports(self) -> None:
        brand_dir = INTEGRATION / "brand"
        for name in ("dark_icon.png", "dark_logo.png", "icon.png", "logo.png"):
            path = brand_dir / name
            self.assertTrue(path.is_file(), f"Missing {path}")
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

        manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "2.0.0")
        self.assertFalse(self.const.DEFAULT_ENABLE_DIAGNOSTIC_ENTITIES)
        self.assertFalse((INTEGRATION / "socket.py").exists())
        self.assertFalse((INTEGRATION / "api.py").exists())

        for rel in ("strings.json", "translations/en.json", "translations/zh-Hans.json"):
            parsed = json.loads((INTEGRATION / rel).read_text(encoding="utf-8"))
            self.assertIn("reauth_confirm", parsed["config"]["step"])
            self.assertIn("reauth_successful", parsed["config"]["abort"])

        for py_file in INTEGRATION.glob("*.py"):
            src = py_file.read_text(encoding="utf-8")
            self.assertNotIn("urllib.request", src, py_file.name)
            self.assertNotIn("import socket", src, py_file.name)
            self.assertNotIn("import threading", src, py_file.name)
            self.assertNotIn("async_add_executor_job", src, py_file.name)
            self.assertNotIn(b"\r\n", py_file.read_bytes(), py_file.name)

    # ---- Pure-Async Loopback TCP Gateway E2E ----
    def test_async_transport_end_to_end_against_loopback_gateway(self) -> None:
        protocol = self.protocol
        control_ack_mode = {"send_ack": True}
        received_controls: list[dict] = []

        async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    try:
                        msg = await self.transport.async_read_frame(reader, timeout=2.0)
                    except (self.codec.DaikinSocketError, TimeoutError):
                        break
                    cmd = msg.get("cmd")
                    if cmd == protocol.CMD_LOGIN:
                        # Send a heartbeat before login OK to exercise heartbeat skipping
                        writer.write(b"\x02\x00\x00\x03")
                        writer.write(protocol.build_frame(request_id=msg["request_id"], cmd_type=protocol.CMD_LOGIN, body=b"\x00\x01"))
                        await writer.drain()
                    elif cmd == protocol.CMD_TRANSFER:
                        inner = msg["inner"]
                        icmd = inner["cmd"]
                        ireq = inner["request_id"]
                        if icmd in (protocol.CMD_GET_ROOM_INFO, protocol.CMD_GET_ROOM_INFO_V1):
                            reply_inner = protocol.build_frame(request_id=ireq, cmd_type=icmd, body=_fixture("room_info.hex"))
                            writer.write(protocol.wrap_transfer(reply_inner, request_id=msg["request_id"]))
                        elif icmd in (protocol.CMD_AIRCON_STATUS_QUERY, protocol.CMD_AIRCON_STATUS_QUERY_V1) and inner["device_type"] == 18:
                            reply_inner = protocol.build_frame(request_id=ireq, cmd_type=icmd, body=_fixture("aircon_status.hex"))
                            writer.write(protocol.wrap_transfer(reply_inner, request_id=msg["request_id"]))
                        elif icmd == protocol.CMD_VAM_STATUS_QUERY and inner["device_type"] == 28:
                            reply_inner = protocol.build_frame(request_id=ireq, cmd_type=icmd, body=_fixture("vam_status.hex"))
                            writer.write(protocol.wrap_transfer(reply_inner, request_id=msg["request_id"]))
                        elif icmd == protocol.CMD_MINIVAM_COMPOSITE_QUERY:
                            comp = bytes([1, 0, 0xAA, 0xBB, 0xCC, 0xDD, 1, 0, 1, 5, 2]) + struct.pack("<H", 225) + b"\x00"
                            reply_inner = protocol.build_frame(request_id=ireq, cmd_type=icmd, body=comp)
                            writer.write(protocol.wrap_transfer(reply_inner, request_id=msg["request_id"]))
                        elif icmd == protocol.CMD_AIR_SENSOR_INFO_2:
                            alias = "客厅".encode("utf-8")
                            body = bytearray([0, 1, 1, 30, 1, 0]) + bytes.fromhex("c8f09e8ab1ac")
                            body.append(len(alias))
                            body.extend(alias)
                            body.extend([0x07, 0x01])
                            body.extend(struct.pack("<hhh", 230, 500, 12))
                            reply_inner = protocol.build_frame(request_id=ireq, cmd_type=icmd, body=bytes(body))
                            writer.write(protocol.wrap_transfer(reply_inner, request_id=msg["request_id"]))
                        elif icmd == protocol.CMD_AIR_SENSOR_STATUS_2:
                            reply_inner = protocol.build_frame(request_id=ireq, cmd_type=icmd, body=_fixture("air_sensor_status.hex"))
                            writer.write(protocol.wrap_transfer(reply_inner, request_id=msg["request_id"]))
                        elif icmd in (protocol.CMD_AIRCON_STATUS_CONTROL, protocol.CMD_VAM_STATUS_CONTROL):
                            received_controls.append(inner)
                            if control_ack_mode["send_ack"]:
                                reply_inner = protocol.build_frame(request_id=ireq, cmd_type=icmd, body=b"\x01\x00")
                                writer.write(protocol.wrap_transfer(reply_inner, request_id=msg["request_id"]))
                        await writer.drain()
            finally:
                writer.close()

        async def _run() -> None:
            server = await asyncio.start_server(_handle_client, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            try:
                gw = self._make_gateway(host="127.0.0.1", port=port)
                client = self.transport.DaikinLocalTransport(gw, nlc_id="nlc_loopback", timeout=3.0)

                devices = await client.async_query_devices()
                self.assertEqual([d.device_type for d in devices], [18, 28, 25])

                statuses = await client.async_query_statuses(devices)
                ac, vam, sensor = devices
                self.assertEqual(statuses[ac.unique_id]["target_temperature"], 24.5)
                self.assertEqual(statuses[vam.unique_id]["air_flow"], 3)
                self.assertEqual(statuses[vam.unique_id]["local_temperature"], 22.5)
                self.assertEqual(statuses[sensor.unique_id]["local_pm25"], 12)
                self.assertEqual(statuses[sensor.unique_id]["local_tvoc_status"], 0)

                # Control + ACK
                res = await client.async_control_device(ac, switch=1, temperature=23.0, ack_timeout=1.0)
                self.assertEqual(res["result"], "accepted")
                self.assertEqual(res["ack_body"], "0100")

                # Control + ACK timeout (does NOT raise!)
                control_ack_mode["send_ack"] = False
                res_timeout = await client.async_control_device(ac, switch=0, ack_timeout=0.15)
                self.assertEqual(res_timeout["result"], "sent_ack_timeout")
                self.assertEqual(len(received_controls), 2)
            finally:
                server.close()
                await server.wait_closed()

        asyncio.run(_run())

    def test_async_read_frame_caps_sync_scan_and_frame_length_and_safe_close(self) -> None:
        async def _run() -> None:
            # 1. Sync-byte scan limit exceeded
            reader = asyncio.StreamReader(limit=self.protocol.MAX_SYNC_SCAN_BYTES)
            reader.feed_data(b"\x00" * (self.protocol.MAX_SYNC_SCAN_BYTES + 10))
            reader.feed_eof()
            with self.assertRaises(self.codec.DaikinSocketError):
                await self.transport.async_read_frame(reader, timeout=1.0)

            # 2. Oversized payload length rejected before reading body
            reader2 = asyncio.StreamReader(limit=self.protocol.MAX_SYNC_SCAN_BYTES)
            reader2.feed_data(b"\x02" + struct.pack("<H", self.protocol.MAX_FRAME_PAYLOAD_LENGTH + 1))
            reader2.feed_eof()
            with self.assertRaises(self.codec.DaikinSocketError):
                await self.transport.async_read_frame(reader2, timeout=1.0)

            # 3. _async_close_writer catches OSError in wait_closed()
            broken_writer = MagicMock()
            broken_writer.wait_closed = AsyncMock(side_effect=OSError("reset by peer"))
            await self.transport._async_close_writer(broken_writer)
            broken_writer.close.assert_called_once()

        asyncio.run(_run())

    # ---- Async DaikinCloudClient Security & Concurrency ----
    def test_cloud_cert_security_https_md5_seclevel1_and_lock(self) -> None:
        async def _run() -> None:
            # 1. Non-HTTPS / empty netloc rejected before GET download
            for bad_url in (
                "http://example.com/cert.p12",
                "file:///etc/passwd",
                "ftp://example.com/cert.p12",
                "https:///missing-host.p12",
                "not-a-url",
            ):
                meta = json.dumps({
                    "code": 0,
                    "data": {"downloadInfo": {"resourcesPath": bad_url, "certPassword": "enc", "md5": "0" * 32}},
                }).encode("utf-8")
                sess = _FakeSession([_FakeResponse(meta)])
                with self.assertRaises(self.codec.DaikinApiError):
                    await self.cloud.async_fetch_client_certificate(sess, "Android:INLS-test", 5.0)
                self.assertEqual(len(sess.calls), 1, f"Should not download {bad_url}")

            # 2. MD5 validation (malformed, mismatch, valid uppercase)
            cert_bytes = b"sample-p12-payload"
            valid_md5 = hashlib.md5(cert_bytes).hexdigest()

            def _meta(md5_val: str) -> bytes:
                return json.dumps({
                    "code": 0,
                    "data": {"downloadInfo": {"resourcesPath": "https://cdn.example.com/client.p12", "certPassword": "enc", "md5": md5_val}},
                }).encode("utf-8")

            with self.assertRaises(self.codec.DaikinApiError):
                await self.cloud.async_fetch_client_certificate(_FakeSession([_FakeResponse(_meta("bad")), _FakeResponse(cert_bytes)]), "p", 5.0)

            wrong_md5 = "0" * 32 if valid_md5 != "0" * 32 else "f" * 32
            with self.assertRaises(self.codec.DaikinApiError):
                await self.cloud.async_fetch_client_certificate(_FakeSession([_FakeResponse(_meta(wrong_md5)), _FakeResponse(cert_bytes)]), "p", 5.0)

            with patch.object(self.cloud, "rsa_public_decrypt_pkcs1_v15_base64", return_value="decrypted_pw"):
                raw, pw = await self.cloud.async_fetch_client_certificate(
                    _FakeSession([_FakeResponse(_meta(valid_md5.upper())), _FakeResponse(cert_bytes)]),
                    "p",
                    5.0,
                )
                self.assertEqual(raw, cert_bytes)
                self.assertEqual(pw, "decrypted_pw")

            # 3. _auth_lock serializes concurrent login & async_close releases mTLS session only
            boot = _FakeSession([])
            client = self.cloud.DaikinCloudClient("u", "p", timeout=5.0, bootstrap_session=boot)
            login_calls = 0

            async def _fake_login_locked():
                nonlocal login_calls
                login_calls += 1
                await asyncio.sleep(0.02)
                client.token = "tok_123"
                client._mtls_session = _FakeSession([])

            with patch.object(client, "_async_login_locked", side_effect=_fake_login_locked):
                await asyncio.gather(client.async_ensure_login(), client.async_ensure_login(), client.async_ensure_login())
            self.assertEqual(login_calls, 1)
            mtls_ref = client._mtls_session
            await client.async_close()
            self.assertTrue(mtls_ref.closed)
            self.assertFalse(boot.closed)

        asyncio.run(_run())

    def test_cloud_build_ssl_context_seclevel1_chmod_and_cleanup(self) -> None:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "daikin-test")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
        p12_bytes = pkcs12.serialize_key_and_certificates(b"test", key, cert, None, BestAvailableEncryption(b"p12pw"))

        created_paths: list[str] = []
        chmod_calls: list[tuple[str, int]] = []
        cipher_calls: list[str] = []
        orig_mkstemp = self.cloud.tempfile.mkstemp
        real_ctx = ssl.create_default_context()

        class _CtxProxy:
            def set_ciphers(self, value):
                cipher_calls.append(value)
                real_ctx.set_ciphers(value)

            def load_cert_chain(self, certfile, keyfile):
                real_ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)

        def _track_mkstemp(*args, **kwargs):
            fd, path = orig_mkstemp(*args, **kwargs)
            created_paths.append(path)
            return fd, path

        with (
            patch.object(self.cloud.tempfile, "mkstemp", side_effect=_track_mkstemp),
            patch.object(self.cloud.os, "name", "posix"),
            patch.object(self.cloud.os, "chmod", side_effect=lambda p, m: chmod_calls.append((p, m))),
            patch.object(self.cloud.ssl, "create_default_context", return_value=_CtxProxy()),
        ):
            self.cloud.build_ssl_context_from_p12(p12_bytes, "p12pw")

        self.assertEqual(cipher_calls, ["DEFAULT@SECLEVEL=1"])
        self.assertEqual(len(created_paths), 2)
        self.assertEqual(len(chmod_calls), 2)
        for path, mode in chmod_calls:
            self.assertEqual(mode, 0o600)
            self.assertFalse(os.path.exists(path))

    # ---- Coordinator: Async Lock, Grace Threshold, Immutability, Smart Control Retry ----
    def test_coordinator_grace_threshold_immutability_and_smart_control_retry(self) -> None:
        hass = _FakeHass()
        entry = self.ha_ce.ConfigEntry(data={"username": "u", "password": "p"}, options={"enable_cloud_snapshot": False})
        coord = self.coordinator_mod.DaikinD611Coordinator(hass, entry)
        self.assertIsInstance(coord._io_lock, asyncio.Lock)
        gw = self._make_gateway()
        coord.gateway = gw
        coord.nlc_id = "nlc123"
        base = self._make_device(18, status={"switch": 1, "target_temperature": 24.0, "local_gateway_available": True, "state_stale": False})
        coord.data = {base.unique_id: base}
        orig_status = dict(base.status)

        async def _run() -> None:
            # 1. 3-strike grace -> 4th raises UpdateFailed; never mutates original snapshot
            with patch.object(coord, "_async_refresh_devices", side_effect=self.codec.DaikinSocketError("offline")):
                for expected in (1, 2, 3):
                    prior = coord.data[base.unique_id]
                    res = await coord._async_update_data()
                    self.assertEqual(coord.consecutive_failures, expected)
                    snap = res[base.unique_id]
                    self.assertIsNot(snap, prior)
                    self.assertTrue(snap.status["state_stale"])
                    self.assertFalse(snap.status["local_gateway_available"])
                    coord.data = res
                self.assertEqual(base.status, orig_status)
                with self.assertRaises(self.ha_uc.UpdateFailed):
                    await coord._async_update_data()

            # 2. Auth error immediately raises ConfigEntryAuthFailed (no grace)
            with patch.object(coord, "_async_refresh_devices", side_effect=self.codec.DaikinAuthError("bad pw")):
                with self.assertRaises(self.ha_exc.ConfigEntryAuthFailed):
                    await coord._async_update_data()

            # 3. Recovery resets consecutive_failures
            fresh = self._make_device(18, status={"switch": 1, "target_temperature": 25.0, "local_gateway_available": True, "state_stale": False})
            with patch.object(coord, "_async_refresh_devices", return_value={fresh.unique_id: fresh}):
                await coord._async_update_data()
                self.assertEqual(coord.consecutive_failures, 0)

            # 4. Smart control retry: sent_ack_timeout does NOT rediscover or resend duplicate command!
            coord.data = {fresh.unique_id: fresh}
            mock_transport = MagicMock()
            mock_transport.async_control_device = AsyncMock(return_value={"result": "sent_ack_timeout", "ack_cmd": 1, "ack_request_id": 2})
            rediscover = AsyncMock()
            with (
                patch.object(coord, "_build_transport", return_value=mock_transport),
                patch.object(coord, "_async_rediscover_gateway", rediscover),
            ):
                await coord.async_control_device(fresh.unique_id, temperature=22.0)
            self.assertEqual(mock_transport.async_control_device.await_count, 1)
            rediscover.assert_not_awaited()
            self.assertEqual(coord.data[fresh.unique_id].status["target_temperature"], 22.0)
            self.assertEqual(fresh.status["target_temperature"], 25.0)  # original immutable!

            # 5. Pre-send connection failure DOES rediscover & retry once
            failing_t = MagicMock()
            failing_t.async_control_device = AsyncMock(side_effect=self.codec.DaikinSocketError("connect refused"))
            retry_t = MagicMock()
            retry_t.async_control_device = AsyncMock(return_value={"result": "accepted", "ack_cmd": 1, "ack_request_id": 5, "ack_body": "01"})
            with (
                patch.object(coord, "_build_transport", side_effect=[failing_t, retry_t]),
                patch.object(coord, "_async_rediscover_gateway", AsyncMock(return_value=self._make_gateway(host="192.168.1.99"))) as red_mock,
            ):
                await coord.async_control_device(fresh.unique_id, switch=0)
            red_mock.assert_awaited_once()
            retry_t.async_control_device.assert_awaited_once()

            # 6. Shutdown cancels delayed refresh and closes cloud mTLS session
            close_mock = AsyncMock()
            with patch.object(coord.cloud, "async_close", close_mock):
                await coord.async_shutdown()
            close_mock.assert_awaited_once()

        asyncio.run(_run())

    # ---- Entity Count Hygiene, Local-First Online, Unique IDs, HA 2027.x APIs ----
    def test_entities_local_first_online_unique_ids_and_ha_2027_compliance(self) -> None:
        hass = _FakeHass()
        entry = self.ha_ce.ConfigEntry(
            entry_id="entry_42",
            data={"username": "user1", "password": "pw1", "host": "192.168.1.99"},
            options={"use_stable_ids": True},  # enable_diagnostic_entities defaults to False!
        )

        # Build the exact 7-device live HAOS topology: 5 AC + 1 Mini-VAM + 1 AirSensor
        devices = {
            d.unique_id: d
            for d in [
                *[self._make_device(18, room_id=i, status={"switch": 1, "mode": 0, "target_temperature": 24.0, "room_temperature": 25.0, "cloud_key": f"INDOOR:{i}", "local_gateway_available": True, "state_stale": False}) for i in range(1, 6)],
                self._make_device(28, room_id=6, status={"switch": 1, "mode": 2, "air_flow": 2, "local_temperature": 23.0, "composite_serial": "a1b2c3d4", "local_gateway_available": True, "state_stale": False}),
                self._make_device(25, room_id=7, status={"local_pm25": 20, "local_co2": 500, "local_tvoc_status": 0, "air_sensor_mac": "c8f09e8ab1ac", "local_gateway_available": True, "state_stale": False}),
            ]
        }

        gateway_device = self.ha_dr.DeviceEntry(id="dev_gw_1", identifiers={(self.const.DOMAIN, "gwkey01")})
        legacy_ac = next(iter(devices.values()))
        legacy_device = self.ha_dr.DeviceEntry(id="dev_legacy_1", identifiers={(self.const.DOMAIN, legacy_ac.unique_id)})
        dr_mock = MagicMock()
        dr_mock.async_get_or_create.return_value = gateway_device
        dr_mock.async_get_device_by_identifier.side_effect = (
            lambda ident, eid: legacy_device if ident == (self.const.DOMAIN, legacy_ac.unique_id) and eid == "entry_42" else None
        )
        er_mock = MagicMock()
        er_mock.async_get_entity_id.return_value = None
        hass.device_registry = dr_mock
        hass.entity_registry = er_mock

        gw = self._make_gateway()

        async def _run() -> None:
            with patch.object(self.coordinator_mod.DaikinD611Coordinator, "_async_refresh_devices", AsyncMock(return_value=devices)):
                orig_init = self.coordinator_mod.DaikinD611Coordinator.__init__

                def _init_gw(self_c, h, e):
                    orig_init(self_c, h, e)
                    self_c.gateway = gw

                with patch.object(self.coordinator_mod.DaikinD611Coordinator, "__init__", _init_gw):
                    self.assertTrue(await self.pkg.async_setup_entry(hass, entry))

            # runtime_data used; NO update listener registered (OptionsFlowWithReload!)
            self.assertEqual(entry.update_listeners, [])
            coord = entry.runtime_data
            self.assertEqual(coord.gateway_device_id, "dev_gw_1")

            # HA 2026.11/2027.x DeviceRegistry API checks
            dr_mock.async_get_device_by_identifier.assert_any_call((self.const.DOMAIN, legacy_ac.unique_id), "entry_42")
            _, update_kwargs = dr_mock.async_update_device.call_args
            self.assertIn("new_identifiers", update_kwargs)
            self.assertNotIn("merge_identifiers", update_kwargs)

            # Collect ALL created entities across all 5 platforms with default options (enable_diagnostic_entities=False)
            created: list = []
            for mod in (self.climate_mod, self.fan_mod, self.select_mod, self.sensor_mod, self.binary_sensor_mod):
                await mod.async_setup_entry(hass, entry, created.extend)

            # 5*9 (AC) + 7 (Mini-VAM) + 14 (AirSensor) = 66 clean entities (down from 108!)
            self.assertEqual(len(created), 66)
            uids = {e._attr_unique_id for e in created}
            for noisy in ("_raw_status", "_last_local_refresh", "_last_cloud_refresh", "_last_control_result", "_local_gateway_binary", "_cloud_snapshot_binary"):
                self.assertFalse(any(uid.endswith(noisy) for uid in uids), f"Noisy entity {noisy} created by default!")

            # Verify exact core unique_ids preserved
            ac_base = legacy_ac.stable_physical_id
            for expected_suffix in ("_climate", "_mode_select", "_fan_select", "_online_binary", "_power_binary", "_target_temperature", "_humidity", "_outdoor_status", "_filter_used_time"):
                self.assertIn(f"{ac_base}{expected_suffix}", uids)

            # When enable_diagnostic_entities=True, all 6 debug entities per device are added AND disabled by default
            entry.options["enable_diagnostic_entities"] = True
            diag_created: list = []
            await self.sensor_mod.async_setup_entry(hass, entry, diag_created.extend)
            await self.binary_sensor_mod.async_setup_entry(hass, entry, diag_created.extend)
            debug_entities = [
                e for e in diag_created
                if any(e._attr_unique_id.endswith(s) for s in ("_raw_status", "_last_local_refresh", "_last_cloud_refresh", "_last_control_result", "_local_gateway_binary", "_cloud_snapshot_binary"))
            ]
            self.assertEqual(len(debug_entities), 7 * 6)
            for e in debug_entities:
                self.assertFalse(e.entity_description.entity_registry_enabled_default)
                self.assertEqual(e.entity_description.entity_category, self.ha_const.EntityCategory.DIAGNOSTIC)

            # Verify Local-first `online` binary sensor across all combinations
            online_desc = self.binary_sensor_mod.COMMON_SENSORS[0]
            for local_v, cloud_v, expected in (
                (True, None, True),
                (True, False, True),
                (True, True, True),
                (False, True, True),
                (False, False, False),
                (False, None, False),
                (None, True, True),
                (None, False, False),
                (None, None, None),
            ):
                d = self._make_device(18, status={})
                if local_v is not None:
                    d.status["local_gateway_available"] = local_v
                if cloud_v is not None:
                    d.status["cloud_online"] = cloud_v
                self.assertEqual(online_desc.value_fn(d), expected, f"Failed for local={local_v}, cloud={cloud_v}")

            # Verify ClimateEntity native_* & DeviceInfo(via_device_id=...)
            climate = self.climate_mod.DaikinD611Climate(coord, legacy_ac.unique_id)
            self.assertEqual(climate.device_info.get("via_device_id"), "dev_gw_1")
            self.assertNotIn("via_device", climate.device_info)
            self.assertEqual(climate._attr_native_temperature_unit, self.ha_const.UnitOfTemperature.CELSIUS)
            self.assertFalse(hasattr(self.climate_mod.DaikinD611Climate, "_attr_temperature_unit"))
            self.assertEqual(climate.native_target_temperature, 24.0)
            self.assertEqual(climate.native_current_temperature, 25.0)

            # Verify modern HA units
            pm25 = next(d for d in self.sensor_mod.AIR_SENSOR_SENSORS if d.key == "pm25")
            co2 = next(d for d in self.sensor_mod.AIR_SENSOR_SENSORS if d.key == "co2")
            flt = next(d for d in self.sensor_mod.AIRCON_SENSORS if d.key == "filter_used_time")
            self.assertEqual(pm25.native_unit_of_measurement, self.ha_const.UnitOfDensity.MICROGRAMS_PER_CUBIC_METER)
            self.assertEqual(co2.native_unit_of_measurement, self.ha_const.UnitOfRatio.PARTS_PER_MILLION)
            self.assertEqual(flt.native_unit_of_measurement, self.ha_const.UnitOfTime.HOURS)

            # Diagnostics redaction + new runtime fields
            diag = await self.diagnostics_mod.async_get_config_entry_diagnostics(hass, entry)
            self.assertEqual(diag["entry"]["data"]["password"], "**REDACTED**")
            self.assertEqual(diag["gateway"]["key"], "**REDACTED**")
            self.assertEqual(diag["consecutive_failures"], 0)
            self.assertIn("last_cloud_snapshot_at", diag)

            # Unload calls coordinator.async_shutdown()
            with patch.object(coord, "async_shutdown", AsyncMock()) as shutdown_mock:
                self.assertTrue(await self.pkg.async_unload_entry(hass, entry))
            shutdown_mock.assert_awaited_once()

        asyncio.run(_run())

    def test_config_flow_reauth_options_and_control_error_wrapping(self) -> None:
        hass = _FakeHass()
        flow = self.config_flow_mod.ConfigFlow()
        flow.hass = hass

        schema = self.config_flow_mod._schema()
        pw_validator = next(v for k, v in schema.schema.items() if getattr(k, "schema", k) == "password")
        self.assertEqual(pw_validator.config.type, "password")

        async def _run() -> None:
            for bad_port in ("0", "65536", "-1", "abc"):
                res = await flow.async_step_user({
                    "username": "u", "password": "p", "gateway": "DTA117D611",
                    "host": "", "port": bad_port, "scan_interval": 60, "timeout": 20,
                })
                self.assertEqual(res["errors"].get("port"), "invalid_port")

            # _async_validate_input always closes cloud even on error
            fake_cloud = MagicMock()
            fake_cloud.async_discover_gateway = AsyncMock(side_effect=self.codec.DaikinAuthError("bad"))
            fake_cloud.async_close = AsyncMock()
            with patch.object(self.config_flow_mod, "DaikinCloudClient", return_value=fake_cloud):
                res = await flow.async_step_user({
                    "username": "u", "password": "p", "gateway": "DTA117D611",
                    "host": "", "port": "", "scan_interval": 60, "timeout": 20,
                })
            self.assertEqual(res["errors"]["base"], "auth")
            fake_cloud.async_close.assert_awaited_once()

            # Reauth & OptionsFlowWithReload (NO custom __init__)
            entry = self.ha_ce.ConfigEntry(entry_id="e_reauth", data={"username": "u1", "password": "p1", "gateway": "DTA117D611"})
            hass.config_entries.async_get_entry.return_value = entry
            flow.context = {"entry_id": "e_reauth"}
            with patch.object(flow, "_async_validate_input", AsyncMock(return_value=self._make_gateway())):
                ok = await flow.async_step_reauth_confirm({"username": "u2", "password": "p2"})
            self.assertEqual(ok["reason"], "reauth_successful")

            opt = self.config_flow_mod.ConfigFlow.async_get_options_flow(entry)
            self.assertIsInstance(opt, self.ha_ce.OptionsFlowWithReload)
            self.assertNotIn("__init__", self.config_flow_mod.OptionsFlowHandler.__dict__)
            opt._ha_config_entry = entry
            form = await opt.async_step_init()
            self.assertEqual(form["step_id"], "init")

            # Control errors wrap in HomeAssistantError and start reauth on DaikinAuthError
            coord = self.coordinator_mod.DaikinD611Coordinator(hass, entry)
            ac = self._make_device(18)
            coord.data = {ac.unique_id: ac}
            climate = self.climate_mod.DaikinD611Climate(coord, ac.unique_id)
            with patch.object(coord, "async_control_device", AsyncMock(side_effect=self.codec.DaikinAuthError("expired"))):
                with self.assertRaises(self.ha_exc.HomeAssistantError):
                    await climate.async_turn_on()
            self.assertTrue(entry.reauth_started)

            entry.reauth_started = False
            with patch.object(coord, "async_control_device", AsyncMock(side_effect=self.codec.DaikinSocketError("down"))):
                with self.assertRaises(self.ha_exc.HomeAssistantError):
                    await climate.async_turn_off()
            self.assertFalse(entry.reauth_started)

        asyncio.run(_run())

    def test_cloud_snapshot_parsing_io_lock_serialization_and_setup_cleanup(self) -> None:
        # 1. calculate_cert_password & parse_cloud_snapshot
        self.assertEqual(len(self.cloud.calculate_cert_password("Android:INLS-test")), 4)
        ac = self._make_device(18, room_id=1, status={})
        vam = self._make_device(28, room_id=2, status={})
        sensor = self._make_device(25, room_id=3, status={})
        sensor.name = "c8f09e8ab1ac"
        snapshot = {
            "ipbox": [{"sub": [{"device_key": "INDOOR:01", "online": 1}]}],
            "indoor": [{
                "key": "INDOOR:01",
                "physics": {"socket_room_id": 1, "name": "客厅"},
                "status": {"switches": "1", "mode": "0", "volume": "3", "temp": "24.5", "outdoor_status": "3"},
                "filter": {"used_time": "120"},
            }],
            "mini_vam": [{
                "key": "VAM:02",
                "online": "true",
                "physics": {"center_address": 1},
                "status": {"switches": 1, "mode": 2, "air_flow": 3},
                "filter": {"filter_used_percent": "45"},
            }],
            "sensor": [{
                "key": "SENSOR:03",
                "online": "0",
                "physics": {"mac": "C8:F0:9E:8A:B1:AC"},
                "status": {"temp": "23.4", "humidity": "52.5", "pm25": "14", "co2": "610"},
            }],
        }
        parsed = self.cloud.parse_cloud_snapshot(snapshot, [ac, vam, sensor], "2026-11-19T00:00:00Z")
        self.assertTrue(parsed[ac.unique_id]["cloud_online"])
        self.assertEqual(parsed[ac.unique_id]["target_temperature"], 24.5)
        self.assertEqual(parsed[ac.unique_id]["filter_used_time"], 120)
        self.assertTrue(parsed[vam.unique_id]["cloud_online"])
        self.assertEqual(parsed[vam.unique_id]["filter_used_percent"], 45)
        self.assertFalse(parsed[sensor.unique_id]["cloud_online"])
        self.assertEqual(parsed[sensor.unique_id]["sensor_temperature"], 23.4)
        self.assertEqual(parsed[sensor.unique_id]["pm25"], 14)

        async def _run() -> None:
            # 2. _io_lock serializes concurrent refresh & control without overlap
            hass = _FakeHass()
            entry = self.ha_ce.ConfigEntry(data={"username": "u", "password": "p"}, options={"enable_cloud_snapshot": False})
            coord = self.coordinator_mod.DaikinD611Coordinator(hass, entry)
            coord.gateway = self._make_gateway()
            coord.nlc_id = "nlc"
            d = self._make_device(18)
            coord.data = {d.unique_id: d}

            active = 0
            overlap = False

            async def _slow_poll(_gw, _prev, *, reuse_cached):
                nonlocal active, overlap
                active += 1
                overlap = overlap or active > 1
                await asyncio.sleep(0.03)
                active -= 1
                return [d.clone(status={})], {d.unique_id: {"switch": 1, "target_temperature": 25.0}}

            async def _slow_ctrl(_dev, **kwargs):
                nonlocal active, overlap
                active += 1
                overlap = overlap or active > 1
                await asyncio.sleep(0.03)
                active -= 1
                return {"result": "accepted"}

            fake_t = MagicMock()
            fake_t.async_control_device = AsyncMock(side_effect=_slow_ctrl)
            with (
                patch.object(coord, "_async_poll_local", side_effect=_slow_poll),
                patch.object(coord, "_build_transport", return_value=fake_t),
            ):
                await asyncio.gather(coord._async_refresh_devices(), coord.async_control_device(d.unique_id, switch=1))
            self.assertFalse(overlap)
            await coord.async_shutdown()

            # 3. Failed async_setup_entry cleans up coordinator/cloud session
            entry2 = self.ha_ce.ConfigEntry(entry_id="fail_entry", data={"username": "u", "password": "p"})
            with (
                patch.object(
                    self.coordinator_mod.DaikinD611Coordinator,
                    "async_config_entry_first_refresh",
                    AsyncMock(side_effect=self.ha_uc.UpdateFailed("boom")),
                ),
                patch.object(self.coordinator_mod.DaikinD611Coordinator, "async_shutdown", AsyncMock()) as sd_mock,
            ):
                with self.assertRaises(self.ha_uc.UpdateFailed):
                    await self.pkg.async_setup_entry(hass, entry2)
            sd_mock.assert_awaited_once()

            # 4. Transport login rejection raises DaikinSocketError
            async def _reject_login(reader, writer):
                try:
                    msg = await self.transport.async_read_frame(reader, timeout=1.0)
                    writer.write(self.protocol.build_frame(request_id=msg["request_id"], cmd_type=self.protocol.CMD_LOGIN, body=b"\x00\x00"))
                    await writer.drain()
                finally:
                    writer.close()

            srv = await asyncio.start_server(_reject_login, "127.0.0.1", 0)
            try:
                port = srv.sockets[0].getsockname()[1]
                t = self.transport.DaikinLocalTransport(self._make_gateway("127.0.0.1", port), nlc_id="nlc", timeout=1.0)
                with self.assertRaises(self.codec.DaikinSocketError):
                    await t.async_query_devices()
            finally:
                srv.close()
                await srv.wait_closed()

            # 5. Legacy unique_id mode (use_stable_ids=False) preserves exact legacy suffixes
            entry3 = self.ha_ce.ConfigEntry(entry_id="legacy_uid", data={"username": "u", "password": "p"}, options={"use_stable_ids": False})
            c3 = self.coordinator_mod.DaikinD611Coordinator(hass, entry3)
            c3.data = {ac.unique_id: ac, vam.unique_id: vam, sensor.unique_id: sensor}
            entry3.runtime_data = c3
            ents: list = []
            for mod in (self.climate_mod, self.fan_mod, self.select_mod, self.sensor_mod, self.binary_sensor_mod):
                await mod.async_setup_entry(hass, entry3, ents.extend)
            uids = {e._attr_unique_id for e in ents}
            self.assertIn(f"{ac.unique_id}_climate", uids)
            self.assertIn(f"{vam.unique_id}_fan", uids)
            self.assertIn(f"{vam.unique_id}_air_flow_select", uids)
            self.assertIn(f"{sensor.unique_id}_pm25", uids)
            self.assertIn(f"{sensor.unique_id}_online_binary", uids)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
