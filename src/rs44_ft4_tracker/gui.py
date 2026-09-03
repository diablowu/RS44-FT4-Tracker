"""图形界面：以地面站为中心的方位角/高度角极坐标图（参考 gpredict 的 Polar View）。

正北在画布正上方，方位角顺时针增大；圆心=天顶(El 90°)，最外圈=地平线(El 0°)，
中间两圈分别是 El 60°/30°。卫星入境（进入过境窗口）后把整段过境的方位角/高度角
轨迹画成一条曲线，并用一个跟随刷新的圆点标出卫星当前位置。

若配置了 radio.preset_freq_pairs（"下行;上行" 频率对，可配多组），窗口里会显示一排
预设按钮；点击某个预设会把 downlink/uplink 标称频率切换过去，并在底部状态栏提示。
"""

from __future__ import annotations

import math
import time
import tkinter as tk
from tkinter import messagebox

from .doppler import PassWindow, azel_track, current_or_next_pass, to_local
from .flrig import FlrigError
from .tracker import Correction, DopplerController, _fmt_secs

_BG = "#f5f7f9"
_GRID = "#8fa3b3"
_GRID_MINOR = "#d3dce2"
_RING_LABEL = "#4a6478"
_COMPASS = "#1b2b3a"
_TRACK = "#c1670a"
_MARKER = "#d63229"
_MARKER_OUTLINE = "#5a0f0f"
_ZENITH = "#4a6478"
_LABEL_FG = "#33475b"
_VALUE_FG = "#0c1620"
_PRESET_BG = "#ffffff"
_PRESET_BG_ACTIVE = "#cfe0f0"
_PRESET_FG = "#0c1620"
_STATUS_FG = "#0a5c2b"

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
        self._marker = self.create_oval(x - r, y - r, x + r, y + r, fill=_MARKER, outline=_MARKER_OUTLINE)


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
    ("aos", "下次入境"),
    ("link", "电台连接"),
    ("preset", "预设"),
)


class TrackerApp:
    """把 DopplerController 的计算结果实时呈现在 Tk 窗口里，不占用终端输出。"""

    def __init__(self, controller: DopplerController, dry_run: bool = False) -> None:
        self.ctl = controller
        self.dry_run = dry_run
        self._track_key: tuple[float, float] | None = None
        self._closed = False
        self._after_id: str | None = None
        self.presets: list[tuple[float, float]] = controller.cfg.radio.presets()
        self._active_preset: int | None = self._find_matching_preset()
        self._preset_buttons: list[tk.Button] = []

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
            tk.Label(info, text=f"{label}：", background=_BG, foreground=_LABEL_FG,
                     font=("TkDefaultFont", 10)).grid(row=row, column=0, sticky="w", pady=2)
            tk.Label(info, textvariable=self.vars[key], background=_BG, foreground=_VALUE_FG,
                     font=("TkDefaultFont", 10, "bold")).grid(row=row, column=1, sticky="w", padx=(6, 0))
        self._set_preset_label()

        if self.presets:
            preset_frame = tk.LabelFrame(self.root, text="预设频率", background=_BG,
                                          foreground=_LABEL_FG, font=("TkDefaultFont", 9))
            preset_frame.grid(row=1, column=0, columnspan=2, sticky="we", padx=12, pady=(0, 6))
            for i, (dl, ul) in enumerate(self.presets):
                btn = tk.Button(
                    preset_frame, text=f"#{i + 1}  {dl:.6f} / {ul:.6f} MHz",
                    font=("TkDefaultFont", 9), relief="groove", bd=1,
                    command=lambda i=i: self._select_preset(i),
                )
                btn.pack(side="left", padx=4, pady=4)
                self._preset_buttons.append(btn)
            self._refresh_preset_buttons()

        self.status_var = tk.StringVar(value="")
        tk.Label(self.root, textvariable=self.status_var, background=_BG, foreground=_STATUS_FG,
                 font=("TkDefaultFont", 9), anchor="w").grid(
            row=2, column=0, columnspan=2, sticky="we", padx=12, pady=(0, 8)
        )

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

        p: PassWindow | None = current_or_next_pass(
            self.ctl.sat, self.ctl.station, self.ctl.sat.now(), self.ctl.cfg.tracking.min_elevation_deg
        )
        self._update_labels(corr, p)
        self.polar.set_marker(corr.geo.az_deg, corr.geo.alt_deg)
        self._update_track(p)

        delay_ms = int(max(0.2, self.ctl.cfg.tracking.interval_s) * 1000)
        self._after_id = self.root.after(delay_ms, self._refresh)

    def _update_track(self, p: PassWindow | None) -> None:
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

    def _update_labels(self, corr: Correction, p: PassWindow | None) -> None:
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
        v["aos"].set(self._fmt_aos(corr, p))
        if self.ctl.rig is None:
            v["link"].set("DRY-RUN（未连接）")
        elif self.ctl._link_down:
            v["link"].set("离线，重试中")
        else:
            v["link"].set(f"已连接 {self.ctl.cfg.flrig.host}:{self.ctl.cfg.flrig.port}")

    @staticmethod
    def _fmt_aos(corr: Correction, p: PassWindow | None) -> str:
        """过境中显示到 LOS 的倒计时，否则显示到下次 AOS 的倒计时。"""
        if p is None:
            return "12 小时内无过境"
        now = time.time()
        if corr.in_pass:
            los_local, _ = to_local(p.los.utc_datetime())
            remain = p.los.utc_datetime().timestamp() - now
            return f"LOS {los_local:%H:%M:%S}（剩余 {_fmt_secs(remain)}）"
        aos_local, _ = to_local(p.aos.utc_datetime())
        remain = p.aos.utc_datetime().timestamp() - now
        return f"AOS {aos_local:%m-%d %H:%M:%S}（{_fmt_secs(remain)} 后，峰值 {p.peak_el_deg:.0f}°）"

    # ------------------------------------------------------------------ 预设频率
    def _find_matching_preset(self) -> int | None:
        dl, ul = self.ctl.cfg.radio.downlink_mhz, self.ctl.cfg.radio.uplink_mhz
        for i, (pdl, pul) in enumerate(self.presets):
            if abs(pdl - dl) < 1e-6 and abs(pul - ul) < 1e-6:
                return i
        return None

    def _set_preset_label(self) -> None:
        if self._active_preset is None:
            self.vars["preset"].set("自定义" if self.presets else "—")
            return
        dl, ul = self.presets[self._active_preset]
        self.vars["preset"].set(f"#{self._active_preset + 1}  {dl:.6f}/{ul:.6f} MHz")

    def _refresh_preset_buttons(self) -> None:
        for i, btn in enumerate(self._preset_buttons):
            active = i == self._active_preset
            btn.configure(background=_PRESET_BG_ACTIVE if active else _PRESET_BG, foreground=_PRESET_FG)

    def _select_preset(self, i: int) -> None:
        dl, ul = self.presets[i]
        self.ctl.cfg.radio.downlink_mhz = dl
        self.ctl.cfg.radio.uplink_mhz = ul
        self._active_preset = i
        self._set_preset_label()
        self._refresh_preset_buttons()
        self._set_status(f"[预设] 已切换到 #{i + 1}：下行 {dl:.6f} MHz / 上行 {ul:.6f} MHz")
        # 立即重算一次以便马上反馈新频率，避免和已排期的刷新重叠成两条并行的定时链
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self._refresh()

    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def _on_close(self) -> None:
        self._closed = True
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self.root.destroy()


def run_gui(controller: DopplerController, dry_run: bool = False) -> None:
    app = TrackerApp(controller, dry_run=dry_run)
    app.start()
