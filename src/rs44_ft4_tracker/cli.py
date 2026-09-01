"""命令行入口：rs44-tracker run / passes。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import AppConfig, ConfigError
from .doppler import Satellite, TleError, load_tle, make_station, next_passes, to_local
from .flrig import FlrigClient, FlrigError
from .tracker import DopplerController


def _add_config_args(p: argparse.ArgumentParser) -> None:
    """所有配置文件字段对应的命令行参数：不填则用配置文件/内置默认值，填了则覆盖。"""
    g_station = p.add_argument_group("台站位置 [station]")
    g_station.add_argument("--locator", default=None, help="Maidenhead 网格坐标，如 OM00aw")
    g_station.add_argument("--latitude", type=float, default=None, help="纬度（十进制度，北正）")
    g_station.add_argument("--longitude", type=float, default=None, help="经度（十进制度，东正）")
    g_station.add_argument("--altitude-m", type=float, default=None, dest="altitude_m", help="海拔（米）")

    g_flrig = p.add_argument_group("flrig [flrig]")
    g_flrig.add_argument("--flrig-host", default=None, dest="host", help="flrig XML-RPC 地址")
    g_flrig.add_argument("--flrig-port", type=int, default=None, dest="port", help="flrig XML-RPC 端口")
    g_flrig.add_argument("--flrig-timeout", type=float, default=None, dest="timeout_s",
                          help="flrig 调用超时（秒）")

    g_sat = p.add_argument_group("卫星 [satellite]")
    g_sat.add_argument("--sat-name", default=None, dest="name", help="卫星名称")
    g_sat.add_argument("--norad-id", type=int, default=None, help="NORAD 编号")
    g_sat.add_argument("--tle-url", default=None, help="TLE 下载地址")
    g_sat.add_argument("--tle-file", default=None, help="本地 TLE 文件路径（优先于网络下载）")
    g_sat.add_argument("--tle-max-age", type=float, default=None, dest="tle_max_age_h",
                        help="TLE 缓存有效期（小时）")

    g_radio = p.add_argument_group("电台 [radio]")
    g_radio.add_argument("--downlink-mhz", type=float, default=None, help="下行标称频率（MHz）")
    g_radio.add_argument("--downlink-mode", default=None, help="下行模式，如 USB-D")
    g_radio.add_argument("--uplink-mhz", type=float, default=None, help="上行标称频率（MHz）")
    g_radio.add_argument("--uplink-mode", default=None, help="上行模式，如 LSB-D")
    g_radio.add_argument("--main-band", choices=("downlink", "uplink"), default=None,
                          help="Main(VFO A) 对应哪条链路")
    g_radio.add_argument("--set-mode-on-start", action=argparse.BooleanOptionalAction, default=None,
                          help="启动时是否下发 Main/Sub 模式")

    g_track = p.add_argument_group("跟踪 [tracking]")
    g_track.add_argument("--interval", type=float, default=None, dest="interval_s", help="校正周期（秒）")
    g_track.add_argument("--min-elevation", type=float, default=None, dest="min_elevation_deg",
                          help="过境判定的最低高度角（度）")
    g_track.add_argument("--retune-threshold", type=float, default=None, dest="retune_threshold_hz",
                          help="重调阈值（Hz）")
    g_track.add_argument("--correct-downlink", action=argparse.BooleanOptionalAction, default=None,
                          help="是否校正下行")
    g_track.add_argument("--correct-uplink", action=argparse.BooleanOptionalAction, default=None,
                          help="是否校正上行")


def _resolve_config(path: str | None) -> str | None:
    if path:
        return path
    if Path("config.toml").exists():
        return "config.toml"
    return None


def _load_config(args: argparse.Namespace) -> AppConfig:
    resolved = _resolve_config(args.config)
    cfg = AppConfig.load(resolved)
    if resolved is None:
        print("[提示] 未找到 config.toml，使用内置默认值（台站位置必须在配置中设置）")
    overridable = AppConfig.override_fields()
    overrides = {k: v for k, v in vars(args).items() if k in overridable and v is not None}
    if overrides:
        cfg = cfg.override(**overrides)
    cfg.station.geodetic()  # 提前触发台站位置校验，给出清晰的错误信息
    return cfg


def cmd_run(args: argparse.Namespace) -> int:
    try:
        cfg = _load_config(args)
    except ConfigError as exc:
        print(f"配置错误: {exc}")
        print("请复制 config.example.toml 为 config.toml 并填写台站位置，或改用命令行参数。")
        return 2

    rig = None
    if not (args.dry_run or args.once):
        rig = FlrigClient(cfg.flrig.host, cfg.flrig.port, cfg.flrig.timeout_s)

    try:
        controller = DopplerController(cfg, rig)
    except TleError as exc:
        print(f"TLE 错误: {exc}")
        return 2

    try:
        controller.run(once=args.once)
    except FlrigError as exc:
        print(f"\n[错误] flrig 通信失败: {exc}")
        print("请确认 flrig 已启动、XML-RPC 服务已开启(Config → XmlRpc)，电台已连接。")
        return 1
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        cfg = _load_config(args)
    except ConfigError as exc:
        print(f"配置错误: {exc}")
        print("请复制 config.example.toml 为 config.toml 并填写台站位置，或改用命令行参数。")
        return 2

    rig = None
    if not args.dry_run:
        rig = FlrigClient(cfg.flrig.host, cfg.flrig.port, cfg.flrig.timeout_s)

    try:
        controller = DopplerController(cfg, rig)
    except TleError as exc:
        print(f"TLE 错误: {exc}")
        return 2

    from .gui import run_gui  # 延迟导入：非 GUI 场景不必加载 tkinter

    run_gui(controller, dry_run=args.dry_run)
    return 0


def cmd_passes(args: argparse.Namespace) -> int:
    try:
        cfg = _load_config(args)
    except ConfigError as exc:
        print(f"配置错误: {exc}")
        print("请复制 config.example.toml 为 config.toml 并填写台站位置，或改用命令行参数。")
        return 2

    try:
        l1, l2 = load_tle(
            cfg.satellite.norad_id, cfg.satellite.name, cfg.satellite.tle_url,
            cfg.satellite.tle_file, cfg.satellite.tle_max_age_h,
        )
        sat = Satellite(l1, l2, cfg.satellite.name)
    except TleError as exc:
        print(f"TLE 错误: {exc}")
        return 2

    lat, lon, alt = cfg.station.geodetic()
    station = make_station(lat, lon, alt)
    min_el = cfg.tracking.min_elevation_deg
    passes = next_passes(
        sat, station, sat.now(), hours=args.hours, min_elevation_deg=min_el,
        max_count=args.count,
    )
    if not passes:
        print(f"未来 {args.hours:g} 小时内没有满足条件的过境（EL≥{min_el:g}°）")
        return 0

    _, tz = to_local(sat.now().utc_datetime())
    print(f"{cfg.satellite.name} (NORAD {cfg.satellite.norad_id}) 未来过境  "
          f"台站 {lat:.4f}, {lon:.4f}  最低高度 {min_el:g}°  时间均为 {tz}")
    print(f"{'#':>2}  {'AOS':<17}{'LOS':<17}{'峰值时刻':<17}{'峰值EL':>7}{'时长':>9}")
    for i, p in enumerate(passes, 1):
        dur = (p.los.utc_datetime().timestamp() - p.aos.utc_datetime().timestamp())
        m, s = divmod(int(dur), 60)
        aos_local, _ = to_local(p.aos.utc_datetime())
        los_local, _ = to_local(p.los.utc_datetime())
        peak_local, _ = to_local(p.max_el.utc_datetime())
        print(f"{i:>2}  {aos_local:%m-%d %H:%M:%S}   "
              f"{los_local:%m-%d %H:%M:%S}   "
              f"{peak_local:%m-%d %H:%M:%S}   "
              f"{p.peak_el_deg:>6.1f}°{m:>6d}m{s:02d}s")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv_list = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog="rs44-tracker",
        description="RS44 FT4 多普勒自动跟踪（flrig XML-RPC 控制 IC-9700 卫星模式 Main/Sub）",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="实时多普勒跟踪（默认命令）")
    p_run.add_argument("-c", "--config", default=None, help="配置文件路径（默认 ./config.toml）")
    p_run.add_argument("--dry-run", action="store_true", help="不连接 flrig，仅显示计算结果")
    p_run.add_argument("--once", action="store_true", help="计算一次并打印报告后退出（不动电台）")
    _add_config_args(p_run)
    p_run.set_defaults(func=cmd_run)

    p_gui = sub.add_parser("gui", help="打开图形界面（方位角/高度角极坐标图），不占用终端输出")
    p_gui.add_argument("-c", "--config", default=None, help="配置文件路径（默认 ./config.toml）")
    p_gui.add_argument("--dry-run", action="store_true", help="不连接 flrig，仅显示计算结果")
    _add_config_args(p_gui)
    p_gui.set_defaults(func=cmd_gui)

    p_pass = sub.add_parser("passes", help="列出未来过境窗口")
    p_pass.add_argument("-c", "--config", default=None, help="配置文件路径（默认 ./config.toml）")
    p_pass.add_argument("--hours", type=float, default=24.0, help="扫描未来小时数（默认 24）")
    p_pass.add_argument("--count", type=int, default=8, help="最多显示几个过境（默认 8）")
    _add_config_args(p_pass)
    p_pass.set_defaults(func=cmd_passes)

    args = parser.parse_args(argv_list)
    if getattr(args, "func", None) is None:
        args = parser.parse_args(["run"] + argv_list)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
