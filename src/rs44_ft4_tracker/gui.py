"""图形界面：以地面站为中心的方位角/高度角极坐标图（参考 gpredict 的 Polar View）。

正北在画布正上方，方位角顺时针增大；圆心=天顶(El 90°)，最外圈=地平线(El 0°)，
中间两圈分别是 El 60°/30°。卫星入境（进入过境窗口）后把整段过境的方位角/高度角
轨迹画成一条曲线，并用一个跟随刷新的圆点标出卫星当前位置。
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import messagebox

from .doppler import PassWindow, azel_track, current_or_next_pass, to_local
from .flrig import FlrigError
from .tracker import Correction, DopplerController

_BG = "#04121f"
_GRID = "#1c3549"
_GRID_MINOR = "#122536"
_RING_LABEL = "#5f87a3"
_COMPASS = "#c9d8e3"
_TRACK = "#e08b2c"
_MARKER = "#ff4d4d"
_ZENITH = "#5f87a3"

_PAD = 30
_RINGS = (60.0, 30.0, 0.0)  # 圆心即 El 90°，不用单独画


class PolarView(tk.Canvas):
    """方位角/高度角极坐标图。"""

    def __init__(self, master: tk.Misc, size: int = 420) -> None:
        super().__init__(master, width=size, height=size, background=_BG, highlightthickness=0)
        self.size = size
        self.cx = size / 2.0
        self.cy = size / 2.0
        self.r_max = size / 2.0 - _PAD
        self._track_ids: list[int] = []
        self._marker: int | None = None
        self._draw_grid()

    def _polar_to_xy(self, az_deg: float, el_deg: float) -> tuple[float, float]:
        el_deg = max(0.0, min(90.0, el_deg))
        r = self.r_max * (90.0 - el_deg) / 90.0
        rad = math.radians(az_deg)
        x = self.cx + r * math.sin(rad)
        y = self.cy - r * math.cos(rad)
        return x, y

    def _draw_grid(self) -> None:
        for el in _RINGS:
            r = self.r_max * (90.0 - el) / 90.0
            self.create_oval(self.cx - r, self.cy - r, self.cx + r, self.cy + r, outline=_GRID, width=1)
            if el > 0:
                self.create_text(self.cx + 4, self.cy - r + 8, text=f"{el:.0f}°",
                                  fill=_RING_LABEL, anchor="w", font=("TkDefaultFont", 8))
        for az in range(0, 360, 30):
            x, y = self._polar_to_xy(az, 0)
            self.create_line(self.cx, self.cy, x, y, fill=_GRID if az % 90 == 0 else _GRID_MINOR, width=1)
        for az, label in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            lx = self.cx + (self.r_max + 14) * math.sin(math.radians(az))
            ly = self.cy - (self.r_max + 14) * math.cos(math.radians(az))
            self.create_text(lx, ly, text=label, fill=_COMPASS, font=("TkDefaultFont", 10, "bold"))
        self.create_oval(self.cx - 2, self.cy - 2, self.cx + 2, self.cy + 2, fill=_ZENITH, outline="")

    def set_track(self, points: list[tuple[float, float]]) -> None:
        for i in self._track_ids:
            self.delete(i)
        self._track_ids.clear()
        coords: list[float] = []
        for az, el in points:
            if el < 0:
                continue
            x, y = self._polar_to_xy(az, el)
            coords.extend((x, y))
        if len(coords) >= 4:
            self._track_ids.append(self.create_line(*coords, fill=_TRACK, width=2, smooth=True))

    def clear_track(self) -> None:
        for i in self._track_ids:
            self.delete(i)
        self._track_ids.clear()

    def set_marker(self, az_deg: float | None, el_deg: float | None) -> None:
        if self._marker is not None:
            self.delete(self._marker)
            self._marker = None
        if az_deg is None or el_deg is None or el_deg < 0:
            return
        x, y = self._polar_to_xy(az_deg, el_deg)
        r = 5
        self._marker = self.create_oval(x - r, y - r, x + r, y + r, fill=_MARKER, outline="#ffffff")


_FIELDS = (
    ("time", "时间"),
    ("az", "方位角"),
    ("el", "高度角"),
    ("range", "斜距"),
    ("rr", "径向速度"),
    ("dl_shift", "下行偏移"),
    ("ul_shift", "上行偏移"),
    ("main_f", "Main 频率"),
    ("sub_f", "Sub 频率"),
    ("state", "状态"),
    ("link", "电台连接"),
)


class TrackerApp:
    """把 DopplerController 的计算结果实时呈现在 Tk 窗口里，不占用终端输出。"""

    def __init__(self, controller: DopplerController, dry_run: bool = False) -> None:
        self.ctl = controller
        self.dry_run = dry_run
        self._track_key: tuple[float, float] | None = None
        self._closed = False
        self._after_id: str | None = None

        self.root = tk.Tk()
        self.root.title(f"RS44 FT4 Tracker — {controller.sat.name}")
        self.root.configure(background=_BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.polar = PolarView(self.root)
        self.polar.grid(row=0, column=0, padx=12, pady=12)

        info = tk.Frame(self.root, background=_BG)
        info.grid(row=0, column=1, sticky="n", padx=(0, 16), pady=12)

        self.vars: dict[str, tk.StringVar] = {key: tk.StringVar(value="—") for key, _ in _FIELDS}
        for row, (key, label) in enumerate(_FIELDS):
            tk.Label(info, text=f"{label}：", background=_BG, foreground=_COMPASS,
                     font=("TkDefaultFont", 10)).grid(row=row, column=0, sticky="w", pady=2)
            tk.Label(info, textvariable=self.vars[key], background=_BG, foreground="#ffffff",
                     font=("TkDefaultFont", 10, "bold")).grid(row=row, column=1, sticky="w", padx=(6, 0))

    # ------------------------------------------------------------------ 启动
    def start(self) -> None:
        if self.ctl.rig is not None:
            try:
                self.ctl.startup_radio()
            except FlrigError as exc:
                messagebox.showerror("flrig 连接失败", str(exc))
                self.root.destroy()
                return
        self._refresh()
        self.root.mainloop()

    # ------------------------------------------------------------------ 刷新
    def _refresh(self) -> None:
        if self._closed:
            return
        corr = self.ctl.compute()
        if self.ctl.rig is not None:
            self.ctl._apply(corr)

        self._update_labels(corr)
        self.polar.set_marker(corr.geo.az_deg, corr.geo.alt_deg)
        self._update_track()

        delay_ms = int(max(0.2, self.ctl.cfg.tracking.interval_s) * 1000)
        self._after_id = self.root.after(delay_ms, self._refresh)

    def _update_track(self) -> None:
        p: PassWindow | None = current_or_next_pass(
            self.ctl.sat, self.ctl.station, self.ctl.sat.now(), self.ctl.cfg.tracking.min_elevation_deg
        )
        if p is None:
            if self._track_key is not None:
                self._track_key = None
                self.polar.clear_track()
            return
        key = (p.aos.utc_datetime().timestamp(), p.los.utc_datetime().timestamp())
        if key != self._track_key:
            self._track_key = key
            track = azel_track(self.ctl.sat, self.ctl.station, p.aos, p.los)
            self.polar.set_track(track)

    def _update_labels(self, corr: Correction) -> None:
        local_dt, tz = to_local(self.ctl.sat.now().utc_datetime())
        dl_shift, ul_shift = corr.shifts(self.ctl.cfg.radio.downlink_hz, self.ctl.cfg.radio.uplink_hz)
        v = self.vars
        v["time"].set(f"{local_dt:%H:%M:%S} {tz}")
        v["az"].set(f"{corr.geo.az_deg:.1f}°")
        v["el"].set(f"{corr.geo.alt_deg:+.1f}°")
        v["range"].set(f"{corr.geo.range_km:.0f} km")
        v["rr"].set(f"{corr.geo.range_rate_km_s:+.2f} km/s")
        v["dl_shift"].set(f"{dl_shift:+.0f} Hz")
        v["ul_shift"].set(f"{ul_shift:+.0f} Hz")
        v["main_f"].set(f"{corr.downlink_hz / 1e6:.6f} MHz")
        v["sub_f"].set(f"{corr.uplink_hz / 1e6:.6f} MHz")
        v["state"].set("过境中" if corr.in_pass else "地平线下")
        if self.ctl.rig is None:
            v["link"].set("DRY-RUN（未连接）")
        elif self.ctl._link_down:
            v["link"].set("离线，重试中")
        else:
            v["link"].set(f"已连接 {self.ctl.cfg.flrig.host}:{self.ctl.cfg.flrig.port}")

    def _on_close(self) -> None:
        self._closed = True
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self.root.destroy()


def run_gui(controller: DopplerController, dry_run: bool = False) -> None:
    app = TrackerApp(controller, dry_run=dry_run)
    app.start()
