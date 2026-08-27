"""DopplerController 行为测试：地平线下也校正、状态行常显多普勒偏移、写入精确到 Hz。"""

from types import SimpleNamespace

from skyfield.api import load

from rs44_ft4_tracker.config import (
    AppConfig,
    FlrigConfig,
    RadioConfig,
    SatelliteConfig,
    StationConfig,
    TrackingConfig,
)
from rs44_ft4_tracker.doppler import Geometry
from rs44_ft4_tracker.tracker import Correction, DopplerController


class FakeRig:
    def __init__(self):
        self.calls = []

    def set_frequency(self, vfo, freq_hz):
        self.calls.append((vfo, freq_hz))


def _make_controller(rig=None, **tracking_kw):
    """构造 DopplerController 但跳过 __init__（避免真的下载 TLE / 建站）。"""
    cfg = AppConfig(
        station=StationConfig(latitude=30.0, longitude=100.0),
        flrig=FlrigConfig(),
        satellite=SatelliteConfig(),
        radio=RadioConfig(),
        tracking=TrackingConfig(**tracking_kw),
    )
    ctl = DopplerController.__new__(DopplerController)
    ctl.cfg = cfg
    ctl.rig = rig
    _ts = load.timescale(builtin=True)
    ctl.sat = SimpleNamespace(now=_ts.now)
    ctl.station = None
    ctl._last_sent = {"downlink": None, "uplink": None}
    ctl._in_pass = None
    ctl._next_aos = None
    ctl._next_aos_checked = 0.0
    ctl._last_warn = 0.0
    return ctl


def _corr(in_pass, dl_hz=435612345, ul_hz=145991000):
    geo = Geometry(
        alt_deg=20.0 if in_pass else -10.0, az_deg=90.0, range_km=2000.0, range_rate_km_s=-1.0
    )
    return Correction(geo=geo, downlink_hz=dl_hz, uplink_hz=ul_hz, in_pass=in_pass)


def test_apply_writes_even_below_horizon():
    """需求1：卫星在地平线下也要修改电台频率。"""
    rig = FakeRig()
    ctl = _make_controller(rig=rig, retune_threshold_hz=1.0)
    ctl._apply(_corr(in_pass=False))
    assert ("A", 435612345) in rig.calls
    assert ("B", 145991000) in rig.calls


def test_apply_respects_threshold_regardless_of_pass():
    rig = FakeRig()
    ctl = _make_controller(rig=rig, retune_threshold_hz=5.0)
    ctl._apply(_corr(in_pass=False, dl_hz=435612000))
    ctl._apply(_corr(in_pass=False, dl_hz=435612003))  # 变化 3Hz < 阈值 5Hz，不重发
    assert rig.calls.count(("A", 435612000)) == 1
    assert all(freq != 435612003 for _, freq in rig.calls)
    ctl._apply(_corr(in_pass=False, dl_hz=435612006))  # 累计变化 6Hz ≥ 阈值，重发
    assert ("A", 435612006) in rig.calls


def test_status_line_shows_shift_below_horizon(monkeypatch):
    """需求2：即使地平线下也要显示多普勒偏移（Hz）。"""
    import rs44_ft4_tracker.tracker as tracker_module

    monkeypatch.setattr(tracker_module, "next_passes", lambda *a, **kw: [])
    ctl = _make_controller(rig=None)
    line = ctl._status_line(_corr(in_pass=False))
    assert "Δ↓" in line and "Δ↑" in line and "Hz" in line
    assert "地平线下" in line


def test_status_line_shows_shift_in_pass():
    ctl = _make_controller(rig=None)
    line = ctl._status_line(_corr(in_pass=True))
    assert "Δ↓" in line and "Δ↑" in line and "过境" in line


def test_compute_rounds_to_integer_hz():
    """需求3：校正频率精确到整数 Hz。"""
    ctl = _make_controller(rig=None)
    geo = Geometry(alt_deg=5.0, az_deg=10.0, range_km=1000.0, range_rate_km_s=2.0)
    ctl.sat = SimpleNamespace(now=lambda: "t", geometry_at=lambda station, t: geo)
    corr = ctl.compute()
    assert isinstance(corr.downlink_hz, int)
    assert isinstance(corr.uplink_hz, int)
    assert corr.downlink_hz != ctl.cfg.radio.downlink_hz  # 确实按多普勒做了偏移
