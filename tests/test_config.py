"""配置加载测试。"""

import pytest

from rs44_ft4_tracker.config import AppConfig, ConfigError


def _write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_defaults_match_rs44_ft4():
    cfg = AppConfig.load(None)
    assert cfg.radio.downlink_mhz == pytest.approx(435.612)
    assert cfg.radio.downlink_mode == "USB-D"
    assert cfg.radio.uplink_mhz == pytest.approx(145.993)
    assert cfg.radio.uplink_mode == "LSB-D"
    assert cfg.radio.main_band == "downlink"
    assert cfg.satellite.norad_id == 44909
    assert cfg.flrig.host == "127.0.0.1" and cfg.flrig.port == 12345
    assert cfg.tracking.correct_downlink and cfg.tracking.correct_uplink
    assert cfg.tracking.retune_threshold_hz == pytest.approx(1.0)  # IC-9700 1 Hz 步进


def test_station_by_locator(tmp_path):
    path = _write(tmp_path, "[station]\nlocator = 'JO65XA'\n")
    lat, lon, alt = AppConfig.load(path).station.geodetic()
    assert lat == pytest.approx(55.020833, abs=1e-4)
    assert lon == pytest.approx(13.958333, abs=1e-4)


def test_station_by_latlon(tmp_path):
    path = _write(tmp_path, "[station]\nlatitude = -33.85\nlongitude = 151.2\naltitude_m = 58\n")
    lat, lon, alt = AppConfig.load(path).station.geodetic()
    assert (lat, lon, alt) == (-33.85, 151.2, 58)


def test_station_missing_raises():
    with pytest.raises(ConfigError, match="台站位置"):
        AppConfig.load(None).station.geodetic()


def test_station_both_provided_raises(tmp_path):
    path = _write(tmp_path, "[station]\nlocator = 'JO65XA'\nlatitude = 1.0\nlongitude = 2.0\n")
    with pytest.raises(ConfigError, match="只能提供一种"):
        AppConfig.load(path).station.geodetic()


def test_partial_override_keeps_defaults(tmp_path):
    path = _write(
        tmp_path,
        "[station]\nlocator = 'OM00aw'\n"
        "[radio]\nuplink_mhz = 145.990\n",
    )
    cfg = AppConfig.load(path)
    assert cfg.radio.uplink_mhz == pytest.approx(145.990)
    assert cfg.radio.downlink_mhz == pytest.approx(435.612)  # 默认保留


def test_missing_file_raises():
    with pytest.raises(ConfigError, match="不存在"):
        AppConfig.load("/nonexistent/config.toml")


def test_bad_main_band(tmp_path):
    path = _write(tmp_path, "[radio]\nmain_band = 'middle'\n")
    with pytest.raises(ConfigError):
        AppConfig.load(path)


def test_main_band_mapping():
    cfg = AppConfig.load(None).with_overrides(interval_s=2.0)
    assert cfg.tracking.interval_s == 2.0
