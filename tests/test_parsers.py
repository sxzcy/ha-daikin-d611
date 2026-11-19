"""Pure protocol parser & frame equivalence tests for Daikin DTA117D611."""

from __future__ import annotations

import importlib
from pathlib import Path
import struct
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
CUSTOM_COMPONENTS = ROOT / "custom_components"
INTEGRATION = CUSTOM_COMPONENTS / "daikin_d611"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
LEGACY_REF = Path(r"d:\UserData\Desktop\anti\tmp\ha-plugins-audit\github\ha-daikin-d611-checkout\custom_components\daikin_d611")


def _ensure_package_stubs() -> None:
    if "custom_components" not in sys.modules:
        pkg = types.ModuleType("custom_components")
        pkg.__path__ = [str(CUSTOM_COMPONENTS)]
        sys.modules["custom_components"] = pkg
    if "custom_components.daikin_d611" not in sys.modules:
        sub = types.ModuleType("custom_components.daikin_d611")
        sub.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.daikin_d611"] = sub


def _fixture(name: str) -> bytes:
    return bytes.fromhex((FIXTURES / name).read_text(encoding="ascii").strip())


class ProtocolParserTests(unittest.TestCase):
    """Verify pure protocol.py against real device hex fixtures and legacy reference."""

    @classmethod
    def setUpClass(cls) -> None:
        _ensure_package_stubs()
        cls.protocol = importlib.import_module("custom_components.daikin_d611.protocol")
        cls.codec = importlib.import_module("custom_components.daikin_d611.codec")
        cls.models = importlib.import_module("custom_components.daikin_d611.models")

    def test_parse_room_info_fixture(self) -> None:
        devices = self.protocol.parse_room_info(
            _fixture("room_info.hex"),
            gateway_id="gateway01",
            gateway_name="DTA117D611",
        )
        self.assertEqual([d.device_type for d in devices], [18, 28, 25])
        self.assertEqual(devices[0].alias, "客厅空调")
        self.assertEqual(devices[1].stable_name, "客厅")
        self.assertEqual(devices[2].alias, "传感器")

    def test_parse_aircon_status_fixture(self) -> None:
        status = self.protocol.parse_aircon_status(_fixture("aircon_status.hex"))
        self.assertEqual(status["room_id"], 1)
        self.assertEqual(status["switch"], 1)
        self.assertEqual(status["mode"], 0)
        self.assertEqual(status["air_flow"], 3)
        self.assertEqual(status["target_temperature"], 24.5)

    def test_parse_vam_status_fixture(self) -> None:
        status = self.protocol.parse_vam_status(_fixture("vam_status.hex"))
        self.assertEqual(status["room_id"], 1)
        self.assertEqual(status["switch"], 1)
        self.assertEqual(status["mode"], 2)
        self.assertEqual(status["air_flow"], 3)

    def test_parse_air_sensor_status_fixture(self) -> None:
        records = self.protocol.parse_air_sensor_status(_fixture("air_sensor_status.hex"))
        self.assertEqual(records[0]["air_sensor_mac"], "c8f09e8ab1ac")
        self.assertEqual(records[0]["local_tvoc_status"], 0)
        self.assertEqual(records[0]["air_sensor_status_tag_1_2"], 7)

    def test_parse_minivam_composite_and_air_sensor_info(self) -> None:
        # Composite TLV: room=1, reserved=0, serial=01020304, st1=1, st2=2, type=3, tag5(2B)=235 (23.5C), tag0, count=1
        comp_body = bytes([1, 0, 1, 2, 3, 4, 1, 2, 3, 5, 2]) + struct.pack("<H", 235) + bytes([0, 1])
        parsed = self.protocol.parse_minivam_composite_status(comp_body)
        self.assertEqual(parsed["composite_serial"], "01020304")
        self.assertEqual(parsed["local_temperature"], 23.5)
        self.assertEqual(parsed["composite_temperature"], 23.5)
        self.assertEqual(parsed["composite_sensor_count"], 1)

        # AirSensor info (cmd 89): resp=0, count=1, room=1, len=40, type=1, unit=0, mac=6B, alias="客厅", type1=0x7F, type2=1
        alias = "客厅".encode("utf-8")
        info_body = bytearray([0, 1, 1, 40, 1, 0])
        info_body.extend(bytes.fromhex("c8f09e8ab1ac"))
        info_body.append(len(alias))
        info_body.extend(alias)
        info_body.extend([0x7F, 0x01])
        info_body.extend(struct.pack("<hhhh", 245, 555, 18, 620))  # temp=24.5, hum=55.5, pm25=18, co2=620
        info_body.append(2)  # voc=2
        info_body.extend(struct.pack("<hh", 35, 4))  # tvoc=0.35, hcho=0.04
        records = self.protocol.parse_air_sensor_info(bytes(info_body))
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["air_sensor_mac"], "c8f09e8ab1ac")
        self.assertEqual(rec["local_sensor_temperature"], 24.5)
        self.assertEqual(rec["local_humidity"], 55.5)
        self.assertEqual(rec["local_pm25"], 18)
        self.assertEqual(rec["local_co2"], 620)
        self.assertEqual(rec["local_voc"], 2)
        self.assertEqual(rec["local_tvoc"], 0.35)
        self.assertEqual(rec["local_hcho"], 0.04)

    def test_parse_frame_validation_and_bounds(self) -> None:
        self.assertEqual(self.protocol.parse_frame(b"\x02\x00\x00\x03")["cmd"], "HEARTBEAT")

        # Valid nested transfer frame round-trip
        cmd, frame = self.protocol.build_control_frame(
            inner_request_id=7, outer_request_id=8, device_type=18, room_id=1,
            switch=1, mode=0, air_flow=3, temperature=24.5,
        )
        self.assertEqual(cmd, 1)
        parsed = self.protocol.parse_frame(frame)
        self.assertEqual(parsed["cmd"], self.protocol.CMD_TRANSFER)
        self.assertEqual(parsed["request_id"], 8)
        self.assertEqual(parsed["inner"]["request_id"], 7)
        self.assertEqual(parsed["inner"]["cmd"], 1)
        self.assertEqual(parsed["inner"]["body"], bytes([1, 0, 1 | 2 | 4 | 16, 1, 0, 3]) + struct.pack("<H", 245))

        # Oversized payload rejected
        bad_len = bytearray(20)
        bad_len[0], bad_len[-1] = 0x02, 0x03
        struct.pack_into("<H", bad_len, 1, self.protocol.MAX_FRAME_PAYLOAD_LENGTH + 1)
        with self.assertRaises(self.codec.DaikinSocketError):
            self.protocol.parse_frame(bytes(bad_len))

        # Invalid header size rejected
        bad_hdr = bytearray(self.protocol.build_frame(request_id=1, cmd_type=16, body=b"ab"))
        bad_hdr[3] = 200
        with self.assertRaises(self.codec.DaikinSocketError):
            self.protocol.parse_frame(bytes(bad_hdr))

    def test_100_percent_equivalence_with_legacy_reference(self) -> None:
        if not (LEGACY_REF / "socket.py").is_file():
            self.skipTest("Legacy reference checkout not present")

        saved = dict(sys.modules)
        try:
            ref_pkg = types.ModuleType("_legacy_daikin_ref")
            ref_pkg.__path__ = [str(LEGACY_REF)]
            sys.modules["_legacy_daikin_ref"] = ref_pkg
            legacy_socket = importlib.import_module("_legacy_daikin_ref.socket")
            legacy_models = importlib.import_module("_legacy_daikin_ref.models")
            LegacyClient = legacy_socket.DaikinSocketClient

            gw = legacy_models.DaikinGateway(
                home_id="h1", home_name="Home", key="gw01", mac="aabbccddeeff",
                name="DTA117D611", gateway_type=1, terminal_type=1, host="127.0.0.1", port=8008,
            )
            legacy = LegacyClient(gw, nlc_id="nlc_user_1", timeout=5.0)

            # 1. Exact parsed fixture equivalence across all 4 hex fixtures
            new_devices = self.protocol.parse_room_info(
                _fixture("room_info.hex"), gateway_id="gw01", gateway_name="DTA117D611",
            )
            old_devices = legacy.parse_room_info({"body": _fixture("room_info.hex")})
            self.assertEqual(len(new_devices), len(old_devices))
            for new_d, old_d in zip(new_devices, old_devices, strict=True):
                for attr in (
                    "gateway_id", "gateway_name", "room_id", "room_name", "room_alias",
                    "device_type", "device_type_name", "unit", "name", "alias",
                    "unique_id", "stable_name", "stable_physical_id", "raw",
                ):
                    self.assertEqual(getattr(new_d, attr), getattr(old_d, attr), f"Mismatch on {attr}")

            self.assertEqual(
                self.protocol.parse_aircon_status(_fixture("aircon_status.hex")),
                LegacyClient.parse_aircon_status(_fixture("aircon_status.hex")),
            )
            self.assertEqual(
                self.protocol.parse_vam_status(_fixture("vam_status.hex")),
                LegacyClient.parse_vam_status(_fixture("vam_status.hex")),
            )
            self.assertEqual(
                self.protocol.parse_air_sensor_status(_fixture("air_sensor_status.hex")),
                LegacyClient.parse_air_sensor_status(_fixture("air_sensor_status.hex")),
            )

            # 2. Byte-for-byte frame builder equivalence
            self.assertEqual(
                self.protocol.build_login_frame(request_id=1, nlc_id="nlc_user_1", gateway_id="gw01", gateway_type=1),
                legacy._build_login_frame(),
            )
            _, new_room_frame = self.protocol.build_room_info_frame(inner_request_id=2, outer_request_id=3, terminal_type=1)
            _, old_room_frame = legacy._build_room_info_frame()
            self.assertEqual(new_room_frame, old_room_frame)

            _, new_ac_frame = self.protocol.build_status_query_frame(
                inner_request_id=4, outer_request_id=5, device_type=18, room_id=1, terminal_type=1,
            )
            _, _, old_ac_frame = legacy._build_status_query_frame(18, 1)
            self.assertEqual(new_ac_frame, old_ac_frame)

            _, new_vam_frame = self.protocol.build_status_query_frame(
                inner_request_id=6, outer_request_id=7, device_type=28, room_id=2, terminal_type=1,
            )
            _, _, old_vam_frame = legacy._build_status_query_frame(28, 2)
            self.assertEqual(new_vam_frame, old_vam_frame)

            _, new_comp_frame = self.protocol.build_minivam_composite_query_frame(
                inner_request_id=8, outer_request_id=9, room_id=2,
            )
            _, _, old_comp_frame = legacy._build_minivam_composite_query_frame(2)
            self.assertEqual(new_comp_frame, old_comp_frame)

            _, new_sensor_frame = self.protocol.build_air_sensor_query_frame(
                inner_request_id=10, outer_request_id=11, cmd=89,
            )
            _, _, old_sensor_frame = legacy._build_air_sensor_query_frame(89)
            self.assertEqual(new_sensor_frame, old_sensor_frame)

            _, new_ctrl_frame = self.protocol.build_control_frame(
                inner_request_id=12, outer_request_id=13, device_type=18, room_id=1,
                switch=1, mode=4, air_flow=2, temperature=25.5,
            )
            _, _, old_ctrl_frame = legacy._build_control_frame(18, 1, switch=1, mode=4, air_flow=2, temperature=25.5)
            self.assertEqual(new_ctrl_frame, old_ctrl_frame)
        finally:
            for key in list(sys.modules):
                if key == "_legacy_daikin_ref" or key.startswith("_legacy_daikin_ref."):
                    sys.modules.pop(key, None)
            sys.modules.update(saved)


if __name__ == "__main__":
    unittest.main()
