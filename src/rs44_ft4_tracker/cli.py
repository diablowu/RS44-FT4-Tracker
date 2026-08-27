"""命令行入口：rs44-tracker run / passes。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import AppConfig, ConfigError
from .doppler import Satellite, TleError, load_tle, make_station, next_passes
from .flrig import FlrigClient, FlrigError
from .tracker import DopplerController


def _resolve_config(path: str | None) -> str | None:
    if path:
        return path
    if Path("config.toml").exists():
        return "config.toml"
    return None


def _load_config(path: str | None) -> AppConfig:
    resolved = _resolve_config(path)
    cfg = AppConfig.load(resolved)
    if resolved is None:
        print("[提示] 未找到 config.toml，使用内置默认值（台站位置必须在配置中设置）")
    cfg.station.geodetic()  # 提前触发台站位置校验，给出行清晰的错误信息
    return cfg


def cmd_run(args: argparse.Namespace) -> int:
    try:
        cfg = _load_config(args.config)
        if args.interval is not None:
            if args.interval <= 0:
                print("错误: --interval 必须为正数")
                return 2
            cfg = cfg.with_overrides(interval_s=args.interval)
    except ConfigError as exc:
        print(f"配置错误: {exc}")
        print("请复制 config.example.toml 为 config.toml 并填写台站位置。")
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


def cmd_passes(args: argparse.Namespace) -> int:
    try:
        cfg = _load_config(args.config)
    except ConfigError as exc:
        print(f"配置错误: {exc}")
        print("请复制 config.example.toml 为 config.toml 并填写台站位置。")
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
    min_el = args.min_elevation if args.min_elevation is not None else cfg.tracking.min_elevation_deg
    passes = next_passes(
        sat, station, sat.now(), hours=args.hours, min_elevation_deg=min_el,
        max_count=args.count,
    )
    if not passes:
        print(f"未来 {args.hours:g} 小时内没有满足条件的过境（EL≥{min_el:g}°）")
        return 0

    print(f"{cfg.satellite.name} (NORAD {cfg.satellite.norad_id}) 未来过境  "
          f"台站 {lat:.4f}, {lon:.4f}  最低高度 {min_el:g}°  时间均为 UTC")
    print(f"{'#':>2}  {'AOS':<17}{'LOS':<17}{'峰值时刻':<17}{'峰值EL':>7}{'时长':>9}")
    for i, p in enumerate(passes, 1):
        dur = (p.los.utc_datetime().timestamp() - p.aos.utc_datetime().timestamp())
        m, s = divmod(int(dur), 60)
        print(f"{i:>2}  {p.aos.utc_datetime():%m-%d %H:%M:%S}   "
              f"{p.los.utc_datetime():%m-%d %H:%M:%S}   "
              f"{p.max_el.utc_datetime():%m-%d %H:%M:%S}   "
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
    p_run.add_argument("--interval", type=float, default=None, help="覆盖校正周期（秒）")
    p_run.set_defaults(func=cmd_run)

    p_pass = sub.add_parser("passes", help="列出未来过境窗口")
    p_pass.add_argument("-c", "--config", default=None, help="配置文件路径（默认 ./config.toml）")
    p_pass.add_argument("--hours", type=float, default=24.0, help="扫描未来小时数（默认 24）")
    p_pass.add_argument("--count", type=int, default=8, help="最多显示几个过境（默认 8）")
    p_pass.add_argument("--min-elevation", type=float, default=None,
                        help="最低高度角（度，默认取配置 min_elevation_deg）")
    p_pass.set_defaults(func=cmd_passes)

    args = parser.parse_args(argv_list)
    if getattr(args, "func", None) is None:
        args = parser.parse_args(["run"] + argv_list)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
