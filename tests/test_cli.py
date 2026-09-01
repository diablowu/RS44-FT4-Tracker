"""命令行参数覆盖配置文件测试。"""

import pytest

from rs44_ft4_tracker.cli import main

_TLE = (
    "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9007\n"
    "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.49813091462617\n"
)


def _write_tle(tmp_path):
    p = tmp_path / "test.tle"
    p.write_text(_TLE, encoding="utf-8")
    return str(p)


def _write_config(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_cli_overrides_config_file(tmp_path, capsys):
    tle = _write_tle(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        "[station]\nlatitude = 30.0\nlongitude = 100.0\n"
        "[radio]\ndownlink_mhz = 435.612\n",
    )
    rc = main([
        "run", "-c", cfg_path, "--dry-run", "--once",
        "--downlink-mhz", "437.612", "--tle-file", tle,
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "437.612000 MHz" in out
    assert "435.612000 MHz" not in out


def test_cli_falls_back_to_config_when_flag_omitted(tmp_path, capsys):
    tle = _write_tle(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        "[station]\nlatitude = 30.0\nlongitude = 100.0\n"
        f"[satellite]\ntle_file = {tle!r}\n"
        "[radio]\ndownlink_mhz = 437.5\n",
    )
    rc = main(["run", "-c", cfg_path, "--dry-run", "--once"])
    assert rc == 0
    assert "437.500000 MHz" in capsys.readouterr().out


def test_cli_station_via_flags_without_config_file(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # 确保当前目录没有 config.toml
    tle = _write_tle(tmp_path)
    rc = main([
        "run", "--dry-run", "--once",
        "--latitude", "30", "--longitude", "100", "--tle-file", tle,
    ])
    assert rc == 0
    assert "配置错误" not in capsys.readouterr().out


def test_cli_invalid_override_reports_config_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    tle = _write_tle(tmp_path)
    rc = main([
        "run", "--dry-run", "--once",
        "--latitude", "30", "--longitude", "100", "--tle-file", tle,
        "--interval", "0",
    ])
    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_cli_unknown_main_band_choice_rejected_by_argparse(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main(["run", "--dry-run", "--once", "--main-band", "middle"])


def test_cli_boolean_flag_overrides_tracking(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    tle = _write_tle(tmp_path)
    rc = main([
        "run", "--dry-run", "--once",
        "--latitude", "30", "--longitude", "100", "--tle-file", tle,
        "--no-correct-uplink",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    # 上行不校正：Sub 调谐频率应与标称频率完全一致，偏移为 0
    assert "Sub 调谐 145.993000 MHz (Δ+0 Hz)" in out
