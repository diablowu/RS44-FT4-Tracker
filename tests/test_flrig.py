"""flrig 客户端测试（本地 mock XML-RPC 服务端，模拟 flrig 行为）。"""

import threading
import xmlrpc.client
from xmlrpc.server import SimpleXMLRPCServer

import pytest

from rs44_ft4_tracker.flrig import FlrigClient, FlrigError

MODES = {"LSB", "USB", "LSB-D", "USB-D", "CW", "FM", "FM-D"}


@pytest.fixture()
def mock_flrig():
    """模拟 flrig 的 rig.* 方法（含字符串形式频率返回，与 flrig 一致）。"""
    server = SimpleXMLRPCServer(("127.0.0.1", 0), logRequests=False)
    state = {"A": 435000000, "B": 145000000, "modeA": "USB-D", "modeB": "LSB-D"}

    server.register_function(lambda: "1.4.7", "main.get_version")
    server.register_function(lambda: "IC-9700", "rig.get_xcvr")
    server.register_function(lambda: str(state["A"]), "rig.get_vfoA")
    server.register_function(lambda: str(state["B"]), "rig.get_vfoB")
    server.register_function(lambda m: _set_freq(state, "A", m), "rig.set_vfoA")
    server.register_function(lambda m: _set_freq(state, "B", m), "rig.set_vfoB")
    server.register_function(lambda: state["modeA"], "rig.get_modeA")
    server.register_function(lambda: state["modeB"], "rig.get_modeB")
    server.register_function(lambda m: _set_mode(state, "A", m), "rig.set_modeA")
    server.register_function(lambda m: _set_mode(state, "B", m), "rig.set_modeB")
    # 真实 flrig 2.0.12 的 IC-9700 驱动 set_modeB 不会自动切到 Sub 波段，
    # FlrigClient.set_mode 用 rig.set_AB 显式切换；mock 只需接受调用。
    server.register_function(lambda vfo: 1, "rig.set_AB")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    yield FlrigClient("127.0.0.1", port, timeout=3.0), state
    server.shutdown()
    thread.join(timeout=3.0)


def _set_freq(state, vfo, freq):
    state[vfo] = int(freq)
    return 1


def _set_mode(state, vfo, mode):
    if mode not in MODES:
        return 0
    state["mode" + vfo] = mode
    return 1


def test_ping_and_xcvr(mock_flrig):
    client, _ = mock_flrig
    assert client.ping() == "1.4.7"
    assert client.get_xcvr() == "IC-9700"


def test_frequency_roundtrip(mock_flrig):
    client, _ = mock_flrig
    client.set_frequency("A", 435612000)
    client.set_frequency("B", 145993456)
    assert client.get_frequency("A") == 435612000
    assert client.get_frequency("B") == 145993456


def test_frequency_string_response_parsed(mock_flrig):
    client, state = mock_flrig
    state["A"] = 435611234  # mock 按 flrig 习惯返回字符串
    assert client.get_frequency("A") == 435611234


def test_mode_set_and_get(mock_flrig):
    client, _ = mock_flrig
    assert client.set_mode("A", "USB-D") is True
    assert client.set_mode("B", "LSB-D") is True
    assert client.get_mode("A") == "USB-D"
    assert client.get_mode("B") == "LSB-D"


def test_unknown_mode_fails(mock_flrig):
    client, _ = mock_flrig
    assert client.set_mode("A", "WFM") is False
    assert client.get_mode("A") == "USB-D"  # 保持不变


def test_setup_sat_pair(mock_flrig):
    client, state = mock_flrig
    client.setup_sat_pair(435612000, "USB-D", 145993000, "LSB-D")
    assert state["A"] == 435612000
    assert state["B"] == 145993000
    assert state["modeA"] == "USB-D"
    assert state["modeB"] == "LSB-D"


def test_setup_bad_mode_raises(mock_flrig):
    client, _ = mock_flrig
    with pytest.raises(FlrigError):
        client.setup_sat_pair(435612000, "USB", 145993000, "LSB-DATA")


def test_connection_refused():
    client = FlrigClient("127.0.0.1", 1, timeout=1.0)  # 端口 1 无服务
    with pytest.raises(FlrigError, match="无法连接"):
        client.ping()
