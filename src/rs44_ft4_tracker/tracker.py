"""主循环：计算多普勒并通过 flrig 实时重调 IC-9700 Main/Sub。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from . import __version__
from .config import AppConfig
from .doppler import (
    Geometry,
    PassWindow,
    Satellite,
    downlink_dial,
    load_tle,
    make_station,
    next_passes,
    to_local,
    uplink_dial,
)
from .flrig import FlrigClient, FlrigError

WARN_INTERVAL_S = 30.0
NEXT_AOS_RECHECK_S = 600.0
MAX_CONSECUTIVE_ERRORS = 5   # 参考 gpredict：连续失败达到该次数后放慢重试节奏
BACKOFF_INTERVAL_S = 10.0    # 电台判定离线后，每隔该秒数才重试一次（而非每周期都等超时）


@dataclass
class Correction:
    """某一时刻对两条链路的调谐结果。"""

    geo: Geometry
    downlink_hz: int
    uplink_hz: int
    in_pass: bool

    def shifts(self, nominal_dl_hz: float, nominal_ul_hz: float) -> tuple[float, float]:
        return self.downlink_hz - nominal_dl_hz, self.uplink_hz - nominal_ul_hz


class DopplerController:
    def __init__(self, cfg: AppConfig, rig: FlrigClient | None = None) -> None:
        self.cfg = cfg
        self.rig = rig
        l1, l2 = load_tle(
            cfg.satellite.norad_id,
            cfg.satellite.name,
            cfg.satellite.tle_url,
            cfg.satellite.tle_file,
            cfg.satellite.tle_max_age_h,
        )
        self.sat = Satellite(l1, l2, cfg.satellite.name)
        lat, lon, alt = cfg.station.geodetic()
        self.station = make_station(lat, lon, alt)
        self._last_sent: dict[str, float | None] = {"downlink": None, "uplink": None}
        self._in_pass: bool | None = None
        self._next_aos: PassWindow | None = None
        self._next_aos_checked: float = 0.0
        self._last_warn: float = 0.0
        self._consecutive_errors: int = 0
        self._link_down: bool = False
        self._last_attempt: float = 0.0

    # ------------------------------------------------------------------ 映射
    def _vfo(self, band: str) -> str:
        """band('downlink'/'uplink') → flrig VFO。Main=A, Sub=B。"""
        if (band == "downlink") == (self.cfg.radio.main_band == "downlink"):
            return "A"
        return "B"

    def _band_mode(self, band: str) -> str:
        return self.cfg.radio.downlink_mode if band == "downlink" else self.cfg.radio.uplink_mode

    def _band_nominal_hz(self, band: str) -> float:
        return self.cfg.radio.downlink_hz if band == "downlink" else self.cfg.radio.uplink_hz

    # ------------------------------------------------------------------ 初始化
    def startup_radio(self) -> None:
        """连通性检查 + 初始模式/标称频率设置。失败直接抛 FlrigError。"""
        assert self.rig is not None
        version = self.rig.ping()
        xcvr = self.rig.get_xcvr()
        print(f"[flrig] 版本 {version}，电台 {xcvr} @ "
              f"{self.cfg.flrig.host}:{self.cfg.flrig.port}")
        if "9700" not in xcvr.replace("-", "").replace(" ", "").lower():
            print(f"[警告] flrig 当前电台为 {xcvr}，非 IC-9700；"
                  f"VFO A/Main、VFO B/Sub 的映射可能不适用，请核对")
        self.rig.setup_sat_pair(
            main_hz=self._band_nominal_hz("downlink") if self._vfo("downlink") == "A"
            else self._band_nominal_hz("uplink"),
            main_mode=self._band_mode("downlink") if self._vfo("downlink") == "A"
            else self._band_mode("uplink"),
            sub_hz=self._band_nominal_hz("uplink") if self._vfo("uplink") == "B"
            else self._band_nominal_hz("downlink"),
            sub_mode=self._band_mode("uplink") if self._vfo("uplink") == "B"
            else self._band_mode("downlink"),
            set_mode=self.cfg.radio.set_mode_on_start,
        )
        self._last_sent = {"downlink": None, "uplink": None}
        print(f"[电台] Main={self.rig.get_frequency('A') / 1e6:.6f} MHz "
              f"{self.rig.get_mode('A')}  Sub={self.rig.get_frequency('B') / 1e6:.6f} MHz "
              f"{self.rig.get_mode('B')}")

    # ------------------------------------------------------------------ 单步
    def compute(self) -> Correction:
        t = self.sat.now()
        geo = self.sat.geometry_at(self.station, t)
        dl = self.cfg.radio.downlink_hz
        ul = self.cfg.radio.uplink_hz
        if self.cfg.tracking.correct_downlink:
            dl = downlink_dial(dl, geo.range_rate_km_s)
        if self.cfg.tracking.correct_uplink:
            ul = uplink_dial(ul, geo.range_rate_km_s)
        in_pass = geo.alt_deg >= self.cfg.tracking.min_elevation_deg
        return Correction(
            geo=geo, downlink_hz=int(round(dl)), uplink_hz=int(round(ul)), in_pass=in_pass
        )

    def _apply(self, corr: Correction) -> None:
        """把校正频率推送到电台（无论卫星是否在地平线上都持续校正；超过阈值才发送）。

        连续失败达到 MAX_CONSECUTIVE_ERRORS 次后判定电台离线：改为每
        BACKOFF_INTERVAL_S 秒才重试一次，避免每个周期都卡在 flrig 的连接超时上
        （否则地平线下的状态行也会跟着变卡）。参考 gpredict 的错误计数/重试策略。
        """
        if self.rig is None:
            return
        now = time.monotonic()
        if self._link_down and now - self._last_attempt < BACKOFF_INTERVAL_S:
            return
        self._last_attempt = now
        threshold = self.cfg.tracking.retune_threshold_hz
        ok = True
        for band, freq in (("downlink", corr.downlink_hz), ("uplink", corr.uplink_hz)):
            last = self._last_sent[band]
            if last is None or abs(freq - last) >= threshold:
                try:
                    self.rig.set_frequency(self._vfo(band), freq)
                    self._last_sent[band] = float(freq)
                except FlrigError as exc:
                    ok = False
                    self._warn(exc)
        if ok:
            if self._link_down:
                print("\n[恢复] 电台连接已恢复")
            self._link_down = False
            self._consecutive_errors = 0
        else:
            self._consecutive_errors += 1
            if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS and not self._link_down:
                self._link_down = True
                print(f"\n[错误] 连续 {self._consecutive_errors} 次连接 flrig 失败，"
                      f"电台可能离线；改为每 {BACKOFF_INTERVAL_S:g}s 重试一次")

    def _warn(self, exc: Exception) -> None:
        now = time.monotonic()
        if now - self._last_warn >= WARN_INTERVAL_S:
            self._last_warn = now
            print(f"\n[警告] {exc}")

    # ------------------------------------------------------------------ 显示
    def _fmt_aos(self) -> str:
        """缓存并返回下一次 AOS 描述。"""
        now = time.monotonic()
        stale = (
            self._next_aos is None
            or self._next_aos.aos.utc_datetime().timestamp() < time.time() - 60
        )
        if stale and now - self._next_aos_checked >= 30.0:
            self._next_aos_checked = now
            passes = next_passes(
                self.sat, self.station, self.sat.now(),
                hours=12.0, min_elevation_deg=self.cfg.tracking.min_elevation_deg, max_count=1,
            )
            self._next_aos = passes[0] if passes else None
        if self._next_aos is None:
            return "12 小时内无过境"
        aos_dt = self._next_aos.aos.utc_datetime()
        remain = aos_dt.timestamp() - time.time()
        local_aos, tz = to_local(aos_dt)
        return f"AOS {local_aos:%m-%d %H:%M:%S} {tz} ({_fmt_secs(remain)} 后, 峰值 {self._next_aos.peak_el_deg:.0f}°)"

    def _status_line(self, corr: Correction) -> str:
        """状态行：无论是否过境都显示多普勒偏移（Hz）与已下发的整 Hz 频率。"""
        local_dt, tz = to_local(self.sat.now().utc_datetime())
        dl_shift, ul_shift = corr.shifts(self.cfg.radio.downlink_hz, self.cfg.radio.uplink_hz)
        base = (
            f"{local_dt:%H:%M:%S} {tz} EL{corr.geo.alt_deg:+06.1f}° AZ{corr.geo.az_deg:05.1f}° "
            f"RR{corr.geo.range_rate_km_s:+05.2f}km/s "
            f"Δ↓{dl_shift:+07.0f}Hz Δ↑{ul_shift:+07.0f}Hz "
            f"Main{corr.downlink_hz / 1e6:.6f} Sub{corr.uplink_hz / 1e6:.6f}"
        )
        if corr.in_pass:
            return base + " [过境]"
        return base + f" [地平线下] 下一圈 {self._fmt_aos()}"

    # ------------------------------------------------------------------ 主循环
    def run(self, once: bool = False) -> None:
        self._print_header()
        if self.rig is not None:
            self.startup_radio()
        try:
            while True:
                corr = self.compute()
                if self._in_pass is not None and corr.in_pass != self._in_pass:
                    local_dt, tz = to_local(self.sat.now().utc_datetime())
                    print(f"\n[{'AOS' if corr.in_pass else 'LOS'}] "
                          f"{local_dt:%H:%M:%S} {tz} "
                          f"EL{corr.geo.alt_deg:+.1f}°")
                    if not corr.in_pass:
                        self._last_sent = {"downlink": None, "uplink": None}
                        self._next_aos_checked = 0.0
                self._in_pass = corr.in_pass
                if once:
                    print(self.report(corr))
                    return
                self._apply(corr)
                print(f"\r{self._status_line(corr):<130}", end="", flush=True)
                time.sleep(max(0.05, self.cfg.tracking.interval_s))
        except KeyboardInterrupt:
            print("\n[退出] Ctrl-C，电台频率保持当前值")

    # ------------------------------------------------------------------ 报告
    def _print_header(self) -> None:
        epoch = self.sat.sat.epoch.utc_datetime()
        age_d = (self.sat.now().utc_datetime() - epoch).total_seconds() / 86400.0
        local_epoch, tz = to_local(epoch)
        lat, lon, alt = self.cfg.station.geodetic()
        mode = "DRY-RUN" if self.rig is None else "LIVE"
        print(
            f"rs44-ft4-tracker v{__version__} [{mode}]  卫星 {self.sat.name} "
            f"(NORAD {self.cfg.satellite.norad_id})\n"
            f"台站 {lat:.4f}°{'N' if lat >= 0 else 'S'} {abs(lon):.4f}°"
            f"{'E' if lon >= 0 else 'W'} 海拔 {alt:.0f} m   "
            f"TLE 历元 {local_epoch:%Y-%m-%d %H:%M} {tz} ({age_d:.1f} 天前)\n"
            f"下行 {self.cfg.radio.downlink_mhz:.6f} MHz {self.cfg.radio.downlink_mode} → Main(A)   "
            f"上行 {self.cfg.radio.uplink_mhz:.6f} MHz {self.cfg.radio.uplink_mode} → Sub(B)   "
            f"周期 {self.cfg.tracking.interval_s:g}s 阈值 {self.cfg.tracking.retune_threshold_hz:g}Hz"
        )

    def report(self, corr: Correction) -> str:
        dl_shift, ul_shift = corr.shifts(self.cfg.radio.downlink_hz, self.cfg.radio.uplink_hz)
        local_dt, tz = to_local(self.sat.now().utc_datetime())
        state = (
            f"过境中（EL≥{self.cfg.tracking.min_elevation_deg:g}°）"
            if corr.in_pass
            else f"地平线下，下一圈 {self._fmt_aos()}"
        )
        return (
            f"\n时刻   {local_dt:%Y-%m-%d %H:%M:%S} {tz}\n"
            f"几何   高度 {corr.geo.alt_deg:+.2f}°  方位 {corr.geo.az_deg:.2f}°  "
            f"斜距 {corr.geo.range_km:.1f} km  径向速度 {corr.geo.range_rate_km_s:+.3f} km/s\n"
            f"下行   {self.cfg.radio.downlink_mhz:.6f} MHz {self.cfg.radio.downlink_mode}"
            f" → Main 调谐 {corr.downlink_hz / 1e6:.6f} MHz (Δ{dl_shift:+.0f} Hz)\n"
            f"上行   {self.cfg.radio.uplink_mhz:.6f} MHz {self.cfg.radio.uplink_mode}"
            f" → Sub 调谐 {corr.uplink_hz / 1e6:.6f} MHz (Δ{ul_shift:+.0f} Hz)\n"
            f"状态   {state}"
        )


def _fmt_secs(secs: float) -> str:
    secs = max(0, int(round(secs)))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}分{s:02d}秒"
