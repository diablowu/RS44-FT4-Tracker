"""多普勒公式与轨道计算测试。"""

import math
from datetime import datetime, timezone

import pytest
from sgp4.api import Satrec, WGS72
from skyfield.api import EarthSatellite, load

from rs44_ft4_tracker.doppler import (
    C_KM_S,
    Satellite,
    azel_track,
    current_or_next_pass,
    downlink_dial,
    geometry,
    make_station,
    next_passes,
    parse_tles,
    tle_sat_number,
    to_local,
    uplink_dial,
)

F_DL = 435.612e6
F_UL = 145.993e6


def test_doppler_signs():
    # 卫星远离 (rr>0)：收到频率变低 → 下行调低；上行要发高
    assert downlink_dial(F_DL, 6.0) < F_DL
    assert uplink_dial(F_UL, 6.0) > F_UL
    # 卫星接近 (rr<0)：下行调高、上行发低
    assert downlink_dial(F_DL, -6.0) > F_DL
    assert uplink_dial(F_UL, -6.0) < F_UL
    # 无径向速度 → 不变
    assert downlink_dial(F_DL, 0.0) == F_DL
    assert uplink_dial(F_UL, 0.0) == F_UL


def test_doppler_magnitude():
    # LEO UHF 最大多普勒约 ±10 kHz 量级
    shift = downlink_dial(F_DL, 7.5) - F_DL
    assert -12_000 < shift < -8_000
    # 上行(145 MHz)修正量约为下行(435 MHz)的 1/3，且符号相反（收低/发高）
    ul_shift = uplink_dial(F_UL, 7.5) - F_UL
    assert ul_shift == pytest.approx(-shift / 3.0, rel=0.01)


def test_parse_tles():
    text = (
        "RS-44\n"
        "1 44909U 19096E   24240.50000000  .00000000  00000-0  00000-0 0  999\n"
        "2 44909  82.5000 200.0000 0010000 100.0000 260.0000 12.50000000100\n"
        "\n"
        "ISS (ZARYA)\n"
        "1 25544U 98067A   24240.50000000  .00000000  00000-0  00000-0 0  999\n"
        "2 25544  51.6000 200.0000 0010000 100.0000 260.0000 15.50000000100\n"
    )
    entries = parse_tles(text)
    assert len(entries) == 2
    assert entries[0][0] == "RS-44"
    assert tle_sat_number(entries[0][1]) == 44909
    assert tle_sat_number(entries[1][1]) == 25544


def _make_sat(alt_km=1500.0, incl_deg=82.5):
    """构造一颗 ~1500 km 圆轨道测试卫星（不依赖网络 TLE）。"""
    from rs44_ft4_tracker.doppler import Satellite

    ts = load.timescale(builtin=True)
    mu = 398600.4418
    a = 6378.137 + alt_km
    period_min = 2 * math.pi * math.sqrt(a**3 / mu) / 60.0
    rec = Satrec()
    epoch_days = (datetime(2026, 8, 27, tzinfo=timezone.utc)
                  - datetime(1949, 12, 31, tzinfo=timezone.utc)).total_seconds() / 86400.0
    rec.sgp4init(
        WGS72, "i", 44909, epoch_days,
        0.0,            # bstar
        0.0,            # ndot
        0.0,            # nddot
        0.001,          # ecc
        0.0,            # argpo
        math.radians(incl_deg),
        0.0,            # mo
        2 * math.pi / period_min,  # no_kozai (rad/min)
        0.0,            # nodeo
    )
    obj = object.__new__(Satellite)
    obj.ts = ts
    obj.sat = EarthSatellite.from_satrec(rec, ts)
    obj.name = "TESTSAT"
    return obj


def test_range_rate_matches_numerical_derivative():
    sat = _make_sat()
    station = make_station(39.9042, 116.4074)
    t = sat.ts.utc(2026, 8, 27, 12, 0, 0)
    g = geometry(sat.sat, station, t)
    # 数值导数交叉验证 d|距离|/dt
    t1 = sat.ts.utc(2026, 8, 27, 11, 59, 59)
    t2 = sat.ts.utc(2026, 8, 27, 12, 0, 1)
    r1 = (sat.sat - station).at(t1).distance().km
    r2 = (sat.sat - station).at(t2).distance().km
    assert g.range_rate_km_s == pytest.approx((r2 - r1) / 2.0, abs=1e-3)
    assert abs(g.range_rate_km_s) < 8.0
    assert -90.0 <= g.alt_deg <= 90.0
    assert 0.0 <= g.az_deg < 360.0


def test_next_passes_finds_windows():
    sat = _make_sat()
    station = make_station(39.9042, 116.4074)
    t0 = sat.ts.utc(2026, 8, 27, 0, 0, 0)
    passes = next_passes(sat, station, t0, hours=24.0, min_elevation_deg=0.0, max_count=20)
    assert len(passes) >= 1, "24 小时内 1500km 轨道在北京上空至少应有 1 次过境"
    for p in passes:
        assert p.los.utc_datetime() > p.aos.utc_datetime()
        assert 0.0 <= p.peak_el_deg <= 90.0
        assert p.aos.utc_datetime() >= t0.utc_datetime()
    # 时间递增
    aos_list = [p.aos.utc_datetime() for p in passes]
    assert aos_list == sorted(aos_list)


def test_to_local_same_instant_as_utc():
    """本地时区转换不改变绝对时刻，只改变显示。"""
    utc = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)
    local, tz = to_local(utc)
    assert local == utc  # 同一时刻
    assert tz  # 非空字符串


def test_azel_track_samples_within_pass_window():
    sat = _make_sat()
    station = make_station(39.9042, 116.4074)
    t0 = sat.ts.utc(2026, 8, 27, 0, 0, 0)
    passes = next_passes(sat, station, t0, hours=24.0, min_elevation_deg=0.0, max_count=1)
    assert passes
    p = passes[0]
    track = azel_track(sat, station, p.aos, p.los, steps=20)
    assert len(track) == 21
    for az, el in track:
        assert 0.0 <= az < 360.0
        assert -90.0 <= el <= 90.0
    # 过境中点应接近峰值仰角附近（粗略上界检查，不要求精确匹配 max_el 采样点）
    assert max(el for _az, el in track) <= p.peak_el_deg + 1.0


def test_azel_track_empty_when_end_not_after_start():
    sat = _make_sat()
    station = make_station(39.9042, 116.4074)
    t0 = sat.ts.utc(2026, 8, 27, 0, 0, 0)
    assert azel_track(sat, station, t0, t0) == []


def test_current_or_next_pass_finds_ongoing_pass():
    sat = _make_sat()
    station = make_station(39.9042, 116.4074)
    t0 = sat.ts.utc(2026, 8, 27, 0, 0, 0)
    passes = next_passes(sat, station, t0, hours=24.0, min_elevation_deg=0.0, max_count=1)
    assert passes
    p = passes[0]
    mid_epoch = (p.aos.utc_datetime().timestamp() + p.los.utc_datetime().timestamp()) / 2.0
    mid_t = sat.ts.utc(datetime.fromtimestamp(mid_epoch, tz=timezone.utc))

    found = current_or_next_pass(sat, station, mid_t, min_elevation_deg=0.0)
    assert found is not None
    assert found.aos.utc_datetime().timestamp() == pytest.approx(p.aos.utc_datetime().timestamp())
    assert found.los.utc_datetime().timestamp() == pytest.approx(p.los.utc_datetime().timestamp())


def test_current_or_next_pass_returns_none_far_from_any_pass(monkeypatch):
    import rs44_ft4_tracker.doppler as doppler_module

    sat = _make_sat()
    station = make_station(39.9042, 116.4074)
    t0 = sat.ts.utc(2026, 8, 27, 0, 0, 0)

    monkeypatch.setattr(doppler_module, "next_passes", lambda *a, **kw: [])
    assert current_or_next_pass(sat, station, t0) is None


def test_to_local_falls_back_to_utc_on_error(monkeypatch):
    """系统时区不可用时（astimezone 抛错）退化为 UTC，而不是崩溃。"""

    class BadDatetime(datetime):
        def astimezone(self, tz=None):
            if tz is None:
                raise OSError("no system timezone")
            return super().astimezone(tz)

    utc = BadDatetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)
    local, tz = to_local(utc)
    assert local == utc
    assert tz == "UTC"
