"""卫星轨道与多普勒计算（skyfield SGP4）。

多普勒约定（rr 为径向速度 km/s，正=远离）：
  - 下行（收）：地面收到 f_rx = f·(1 - rr/c)，把电台调到该频率即可对准信号；
  - 上行（发）：要让卫星收到标称 f，需发射 f_tx = f/(1 - rr/c)。
两条链路各按单向多普勒独立修正（线性转发器全双工的标准做法）。
"""

from __future__ import annotations

import os
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from skyfield.api import EarthSatellite, load, wgs84
from skyfield.toposlib import GeographicPosition
from skyfield.timelib import Timescale, Time

C_KM_S = 299792.458  # 光速 km/s


class TleError(RuntimeError):
    """TLE 获取/解析失败。"""


# ---------------------------------------------------------------------- 多普勒
def downlink_dial(freq_hz: float, range_rate_km_s: float) -> float:
    """给定卫星径向速度，返回下行接收应调谐的频率 (Hz)。"""
    return freq_hz * (1.0 - range_rate_km_s / C_KM_S)


def uplink_dial(freq_hz: float, range_rate_km_s: float) -> float:
    """给定卫星径向速度，返回上行应发射的频率 (Hz)。"""
    return freq_hz / (1.0 - range_rate_km_s / C_KM_S)


# ---------------------------------------------------------------------- TLE
def parse_tles(text: str) -> list[tuple[str | None, str, str]]:
    """把 TLE 文本解析为 [(名称, line1, line2), ...]。"""
    entries: list[tuple[str | None, str, str]] = []
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    i = 0
    while i < len(lines):
        if lines[i].startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
            entries.append((None, lines[i], lines[i + 1]))
            i += 2
        elif (
            i + 2 < len(lines)
            and lines[i + 1].startswith("1 ")
            and lines[i + 2].startswith("2 ")
        ):
            entries.append((lines[i].strip(), lines[i + 1], lines[i + 2]))
            i += 3
        else:
            i += 1
    return entries


def tle_sat_number(line1: str) -> int | None:
    m = re.match(r"^1 (\d{5})", line1)
    return int(m.group(1)) if m else None


def fetch_tle(url: str, timeout: float = 20.0) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "rs44-ft4-tracker/0.1 (amateur radio doppler control)"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read().decode("utf-8", errors="replace")
    if "1 " not in data:
        raise TleError(f"{url} 返回内容不含 TLE: {data[:100]!r}")
    return data


def cache_path(norad_id: int) -> Path:
    base = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    d = Path(base) / "rs44_ft4_tracker"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"tle_{norad_id}.txt"


def load_tle(
    norad_id: int,
    name: str,
    url: str,
    local_file: str = "",
    max_age_h: float = 12.0,
) -> tuple[str, str]:
    """获取 TLE：本地文件优先；否则用缓存，过期/缺失则从网络刷新。

    网络失败但存在（过期）缓存时发出警告并继续使用。
    """
    if local_file:
        text = Path(local_file).read_text(encoding="utf-8")
    else:
        cp = cache_path(norad_id)
        age_h = time.time() - cp.stat().st_mtime if cp.exists() else None
        if cp.exists() and age_h is not None and age_h < max_age_h:
            text = cp.read_text(encoding="utf-8")
        else:
            try:
                text = fetch_tle(url)
                cp.write_text(text, encoding="utf-8")
            except OSError as exc:
                if cp.exists():
                    print(f"[警告] TLE 下载失败（{exc}），使用过期缓存 {cp}")
                    text = cp.read_text(encoding="utf-8")
                else:
                    raise TleError(
                        f"无法下载 TLE（{exc}），且无本地缓存。"
                        f"可在配置 satellite.tle_file 指定本地 TLE 文件。"
                    ) from exc

    entries = parse_tles(text)
    if not entries:
        raise TleError("TLE 内容为空或格式错误")
    for _nm, l1, l2 in entries:
        if tle_sat_number(l1) == norad_id:
            return l1, l2
    if len(entries) == 1:
        return entries[0][1], entries[0][2]
    numbers = ", ".join(str(tle_sat_number(l1)) for _n, l1, _l2 in entries)
    raise TleError(f"TLE 中未找到 NORAD {norad_id}（现有: {numbers}）")


# ---------------------------------------------------------------------- 几何
@dataclass(frozen=True)
class Geometry:
    """某一时刻的卫星观测几何。"""

    alt_deg: float
    az_deg: float
    range_km: float
    range_rate_km_s: float  # 正 = 远离


def geometry(sat: EarthSatellite, station: GeographicPosition, t: Time) -> Geometry:
    """计算高度角/方位角/距离/径向速度。

    径向速度用 d|位置|/dt = 位置·速度/|位置| 计算（相对速度已含测站随地球自转）。
    """
    topoc = (sat - station).at(t)
    alt, az, distance = topoc.altaz()
    pos = topoc.position.km
    vel = topoc.velocity.km_per_s
    rr = float(np.dot(pos, vel) / np.linalg.norm(pos))
    return Geometry(
        alt_deg=float(alt.degrees),
        az_deg=float(az.degrees),
        range_km=float(distance.km),
        range_rate_km_s=rr,
    )


class Satellite:
    """封装 TLE 加载与常用查询。"""

    def __init__(self, l1: str, l2: str, name: str = "RS-44") -> None:
        self.ts: Timescale = load.timescale(builtin=True)
        self.sat = EarthSatellite(l1, l2, name, self.ts)
        self.name = name

    @classmethod
    def from_tle_lines(cls, l1: str, l2: str, name: str = "RS-44") -> "Satellite":
        return cls(l1, l2, name)

    def now(self) -> Time:
        return self.ts.now()

    def geometry_at(self, station: GeographicPosition, t: Time) -> Geometry:
        return geometry(self.sat, station, t)


def make_station(lat_deg: float, lon_deg: float, alt_m: float = 0.0) -> GeographicPosition:
    return wgs84.latlon(lat_deg, lon_deg, elevation_m=alt_m)


@dataclass(frozen=True)
class PassWindow:
    aos: Time
    max_el: Time
    los: Time
    peak_el_deg: float


def next_passes(
    sat: Satellite,
    station: GeographicPosition,
    t0: Time,
    hours: float = 24.0,
    min_elevation_deg: float = 0.0,
    coarse_step_s: float = 30.0,
    max_count: int = 10,
) -> list[PassWindow]:
    """扫描未来 hours 小时内的过境窗口（AOS/LOS 时刻精度约 ±步长/2）。"""
    start = t0.utc_datetime().timestamp()
    n = int(hours * 3600.0 / coarse_step_s) + 2
    dts = [
        datetime.fromtimestamp(start + i * coarse_step_s, tz=timezone.utc) for i in range(n)
    ]
    times = t0.ts.utc(dts)
    elevations = list((sat.sat - station).at(times).altaz()[0].degrees)

    result: list[PassWindow] = []
    window: list[tuple[float, float]] | None = None  # [(epoch_s, elev), ...]
    for dt, el in zip(dts, elevations):
        epoch = dt.timestamp()
        if el >= min_elevation_deg:
            if window is None:
                window = []
            window.append((epoch, el))
        elif window:
            result.append(_make_window(sat.ts, window, coarse_step_s))
            if len(result) >= max_count:
                return result
            window = None
    if window:
        result.append(_make_window(sat.ts, window, coarse_step_s))
    return result


def _make_window(
    ts: Timescale, samples: list[tuple[float, float]], coarse_step_s: float
) -> PassWindow:
    aos_epoch = samples[0][0] - coarse_step_s / 2.0
    los_epoch = samples[-1][0] + coarse_step_s / 2.0
    peak = max(samples, key=lambda s: s[1])
    return PassWindow(
        aos=ts.utc(datetime.fromtimestamp(aos_epoch, tz=timezone.utc)),
        max_el=ts.utc(datetime.fromtimestamp(peak[0], tz=timezone.utc)),
        los=ts.utc(datetime.fromtimestamp(los_epoch, tz=timezone.utc)),
        peak_el_deg=peak[1],
    )
