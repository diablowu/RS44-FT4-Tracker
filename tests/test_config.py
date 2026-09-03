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
    cfg = AppConfig.load(None).override(interval_s=2.0)
    assert cfg.tracking.interval_s == 2.0


def test_override_crosses_multiple_sections():
    cfg = AppConfig.load(None).override(
        latitude=1.0, longitude=2.0, host="10.0.0.1", downlink_mhz=145.9, interval_s=2.0
    )
    assert (cfg.station.latitude, cfg.station.longitude) == (1.0, 2.0)
    assert cfg.flrig.host == "10.0.0.1"
    assert cfg.radio.downlink_mhz == pytest.approx(145.9)
    assert cfg.tracking.interval_s == pytest.approx(2.0)
    # 未覆盖的字段保持原值
    assert cfg.radio.uplink_mhz == pytest.approx(145.993)


def test_override_unknown_field_raises():
    with pytest.raises(ConfigError, match="未知配置项"):
        AppConfig.load(None).override(not_a_real_field=1)


def test_override_reruns_radio_validation():
    with pytest.raises(ConfigError):
        AppConfig.load(None).override(main_band="middle")


def test_preset_freq_pairs_parsed(tmp_path):
    path = _write(
        tmp_path,
        "[station]\nlocator = 'OM00aw'\n"
        "[radio]\npreset_freq_pairs = ['435.611000;145.990150', '435.610000;145.991000']\n",
    )
    cfg = AppConfig.load(path)
    assert cfg.radio.presets() == [(435.611, 145.99015), (435.610, 145.991)]


def test_preset_freq_pairs_bad_format_raises(tmp_path):
    path = _write(tmp_path, "[radio]\npreset_freq_pairs = ['not-a-pair']\n")
    with pytest.raises(ConfigError, match="格式错误"):
        AppConfig.load(path)


def test_preset_freq_pairs_non_numeric_raises(tmp_path):
    path = _write(tmp_path, "[radio]\npreset_freq_pairs = ['abc;def']\n")
    with pytest.raises(ConfigError, match="不是合法数字"):
        AppConfig.load(path)


def test_preset_freq_pairs_via_override():
    cfg = AppConfig.load(None).override(preset_freq_pairs=["435.611000;145.990150"])
    assert cfg.radio.presets() == [(435.611, 145.99015)]
