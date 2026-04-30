from pathlib import Path
import sys
import types

ROOT = Path(__file__).parents[1]
CUSTOM_COMPONENTS = ROOT / "custom_components"
INTEGRATION = CUSTOM_COMPONENTS / "daikin_d611"

custom_components = types.ModuleType("custom_components")
custom_components.__path__ = [str(CUSTOM_COMPONENTS)]
sys.modules.setdefault("custom_components", custom_components)

daikin_package = types.ModuleType("custom_components.daikin_d611")
daikin_package.__path__ = [str(INTEGRATION)]
sys.modules.setdefault("custom_components.daikin_d611", daikin_package)

from custom_components.daikin_d611.socket import DaikinSocketClient  # noqa: E402


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> bytes:
    return bytes.fromhex((FIXTURES / name).read_text(encoding="ascii").strip())


def test_parse_room_info_fixture():
    client = DaikinSocketClient.__new__(DaikinSocketClient)
    client.gateway = type("Gateway", (), {"id": "gateway01", "name": "DTA117D611"})()

    devices = client.parse_room_info({"body": _fixture("room_info.hex")})

    assert [device.device_type for device in devices] == [18, 28, 25]
    assert devices[0].alias == "客厅空调"
    assert devices[1].stable_name == "客厅"
    assert devices[2].alias == "传感器"


def test_parse_aircon_status_fixture():
    status = DaikinSocketClient.parse_aircon_status(_fixture("aircon_status.hex"))

    assert status["room_id"] == 1
    assert status["switch"] == 1
    assert status["mode"] == 0
    assert status["air_flow"] == 3
    assert status["target_temperature"] == 24.5


def test_parse_vam_status_fixture():
    status = DaikinSocketClient.parse_vam_status(_fixture("vam_status.hex"))

    assert status["room_id"] == 1
    assert status["switch"] == 1
    assert status["mode"] == 2
    assert status["air_flow"] == 3


def test_parse_air_sensor_status_fixture():
    records = DaikinSocketClient.parse_air_sensor_status(_fixture("air_sensor_status.hex"))

    assert records[0]["air_sensor_mac"] == "c8f09e8ab1ac"
    assert records[0]["local_tvoc_status"] == 0
    assert records[0]["air_sensor_status_tag_1_2"] == 7
