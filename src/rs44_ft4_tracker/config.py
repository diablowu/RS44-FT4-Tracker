"""TOML 配置文件加载与默认值。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

from .maidenhead import GridError, grid_to_latlon


class ConfigError(ValueError):
    """配置错误。"""


@dataclass
class StationConfig:
    """台站位置：locator（Maidenhead 网格）或 latitude/longitude（十进制度）。"""

    locator: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float = 0.0

    def geodetic(self) -> tuple[float, float, float]:
        """返回 (纬度°, 经度°, 海拔 m)；locator 与经纬度二选一。"""
        if self.locator and (self.latitude is not None or self.longitude is not None):
            raise ConfigError("station.locator 与 station.latitude/longitude 只能提供一种")
        if self.locator:
            try:
                lat, lon = grid_to_latlon(self.locator)
            except GridError as exc:
                raise ConfigError(f"station.locator 无效: {exc}") from exc
            return lat, lon, self.altitude_m
        if self.latitude is None or self.longitude is None:
            raise ConfigError(
                "缺少台站位置：请在配置文件 [station] 里填写 locator（如 OM00aw）"
                "或 latitude/longitude（十进制度）"
            )
        if not -90.0 <= self.latitude <= 90.0:
            raise ConfigError(f"station.latitude 超出 ±90°: {self.latitude}")
        if not -180.0 <= self.longitude <= 180.0:
            raise ConfigError(f"station.longitude 超出 ±180°: {self.longitude}")
        return self.latitude, self.longitude, self.altitude_m


@dataclass
class FlrigConfig:
    host: str = "127.0.0.1"
    port: int = 12345
    timeout_s: float = 5.0


@dataclass
class SatelliteConfig:
    name: str = "RS-44"
    norad_id: int = 44909
    tle_url: str = "https://celestrak.org/NORAD/elements/gp.php?CATNR=44909&FORMAT=TLE"
    tle_file: str = ""  # 非空则优先使用本地 TLE 文件（离线）
    tle_max_age_h: float = 12.0  # 缓存超过该小时数则自动重新下载


@dataclass
class RadioConfig:
    downlink_mhz: float = 435.612
    downlink_mode: str = "USB-D"
    uplink_mhz: float = 145.993
    uplink_mode: str = "LSB-D"
    set_mode_on_start: bool = True
    # IC-9700 卫星模式：Main 对应哪条链路（另一侧自动为 Sub）。
    # flrig 中 VFO A = Main，VFO B = Sub。
    main_band: str = "downlink"
    # 预设频率对："下行;上行"（MHz），如 "435.611000;145.990150"；可配多组，供 GUI 切换。
    preset_freq_pairs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.main_band not in ("downlink", "uplink"):
            raise ConfigError(f"radio.main_band 只能是 downlink/uplink: {self.main_band!r}")
        if self.downlink_mhz <= 0 or self.uplink_mhz <= 0:
            raise ConfigError("radio.downlink_mhz / uplink_mhz 必须为正数")
        self.presets()  # 提前校验格式，配错立刻报错而不是等 GUI 里点了才发现

    @property
    def downlink_hz(self) -> float:
        return self.downlink_mhz * 1e6

    @property
    def uplink_hz(self) -> float:
        return self.uplink_mhz * 1e6

    def presets(self) -> list[tuple[float, float]]:
        """把 preset_freq_pairs 解析成 (下行MHz, 上行MHz) 元组列表。"""
        result: list[tuple[float, float]] = []
        for i, raw in enumerate(self.preset_freq_pairs, 1):
            parts = raw.split(";")
            if len(parts) != 2:
                raise ConfigError(
                    f"radio.preset_freq_pairs[{i}] 格式错误，应为 '下行;上行'"
                    f"（如 '435.611000;145.990150'）: {raw!r}"
                )
            try:
                dl, ul = float(parts[0]), float(parts[1])
            except ValueError as exc:
                raise ConfigError(f"radio.preset_freq_pairs[{i}] 不是合法数字: {raw!r}") from exc
            if dl <= 0 or ul <= 0:
                raise ConfigError(f"radio.preset_freq_pairs[{i}] 频率必须为正数: {raw!r}")
            result.append((dl, ul))
        return result


@dataclass
class TrackingConfig:
    interval_s: float = 1.0
    min_elevation_deg: float = 0.0
    retune_threshold_hz: float = 1.0  # IC-9700 支持 1 Hz 步进；变化小于该值不重调
    correct_downlink: bool = True
    correct_uplink: bool = True

    def __post_init__(self) -> None:
        if self.interval_s <= 0:
            raise ConfigError("tracking.interval_s 必须为正数")
        if self.retune_threshold_hz < 0:
            raise ConfigError("tracking.retune_threshold_hz 不能为负数")


_SECTION_TYPES = {
    "station": StationConfig,
    "flrig": FlrigConfig,
    "satellite": SatelliteConfig,
    "radio": RadioConfig,
    "tracking": TrackingConfig,
}


@dataclass
class AppConfig:
    station: StationConfig
    flrig: FlrigConfig
    satellite: SatelliteConfig
    radio: RadioConfig
    tracking: TrackingConfig

    @classmethod
    def load(cls, path: str | Path | None) -> "AppConfig":
        """加载配置；path 为空时使用全部默认值（仅缺台站位置时会报错）。"""
        data: dict = {}
        if path is not None:
            p = Path(path)
            if not p.exists():
                raise ConfigError(f"配置文件不存在: {p}")
            with p.open("rb") as fh:
                data = tomllib.load(fh)

        def build(section_dc, section_dict, coercions=None):
            kwargs = {}
            for f in fields(section_dc):
                if section_dict and f.name in section_dict:
                    val = section_dict[f.name]
                    if coercions and f.name in coercions:
                        val = coercions[f.name](val)
                    kwargs[f.name] = val
            return section_dc(**kwargs)

        return cls(
            station=build(
                StationConfig,
                data.get("station", {}),
                coercions={
                    "latitude": float,
                    "longitude": float,
                    "altitude_m": float,
                },
            ),
            flrig=build(FlrigConfig, data.get("flrig", {}), {"port": int, "timeout_s": float}),
            satellite=build(
                SatelliteConfig, data.get("satellite", {}), {"norad_id": int, "tle_max_age_h": float}
            ),
            radio=build(
                RadioConfig,
                data.get("radio", {}),
                {"downlink_mhz": float, "uplink_mhz": float},
            ),
            tracking=build(
                TrackingConfig,
                data.get("tracking", {}),
                {
                    "interval_s": float,
                    "min_elevation_deg": float,
                    "retune_threshold_hz": float,
                },
            ),
        )

    @staticmethod
    def override_fields() -> dict[str, str]:
        """所有可覆盖字段名 -> 所属 section 名（用于命令行参数按字段名覆盖配置）。"""
        mapping: dict[str, str] = {}
        for section_name, dc in _SECTION_TYPES.items():
            for f in fields(dc):
                mapping[f.name] = section_name
        return mapping

    def override(self, **kwargs) -> "AppConfig":
        """按字段名覆盖任意 section 的配置项（跨 station/flrig/satellite/radio/tracking
        自动定位所属 section）。调用方应先过滤掉未提供（None）的项再传入。
        """
        owner = self.override_fields()
        by_section: dict[str, dict] = {name: {} for name in _SECTION_TYPES}
        for key, val in kwargs.items():
            if key not in owner:
                raise ConfigError(f"未知配置项: {key}")
            by_section[owner[key]][key] = val

        sections = {
            "station": self.station,
            "flrig": self.flrig,
            "satellite": self.satellite,
            "radio": self.radio,
            "tracking": self.tracking,
        }
        for name, updates in by_section.items():
            if updates:
                sections[name] = replace(sections[name], **updates)
        return AppConfig(**sections)
