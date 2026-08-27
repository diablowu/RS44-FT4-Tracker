"""Maidenhead 网格坐标转经纬度（支持 4/6/8 位网格，返回网格中心点）。"""

from __future__ import annotations


class GridError(ValueError):
    """网格坐标格式错误。"""


def grid_to_latlon(grid: str) -> tuple[float, float]:
    """把 Maidenhead 网格（如 ``JO65XA`` / ``JO65XA56``）转换为 (纬度, 经度)。

    返回该网格单元中心点的十进制度数。北纬/东经为正。
    """
    g = grid.strip().upper()
    if len(g) not in (4, 6, 8):
        raise GridError(f"网格长度应为 4/6/8 位: {grid!r}")
    for ch in g[0:2] + (g[4:6] if len(g) >= 8 else ""):
        if not ("A" <= ch <= "R"):
            raise GridError(f"字段/子方格字符超出 A-R 范围: {grid!r}")
    for ch in g[2:4] + (g[6:8] if len(g) == 8 else ""):
        if not ch.isdigit():
            raise GridError(f"方格字符应为数字: {grid!r}")

    lon = -180.0 + 20.0 * (ord(g[0]) - 65) + 2.0 * (ord(g[2]) - 48)
    lat = -90.0 + 10.0 * (ord(g[1]) - 65) + 1.0 * (ord(g[3]) - 48)

    if len(g) == 4:
        lon += 1.0
        lat += 0.5
    else:
        # 第 5、6 位缩小到 5 分(经) / 2.5 分(纬)
        lon += 5.0 / 60.0 * (ord(g[4]) - 65) + 5.0 / 120.0
        lat += 2.5 / 60.0 * (ord(g[5]) - 65) + 2.5 / 120.0
        if len(g) == 8:
            # 第 7、8 位再缩小 1/24：2.5 秒(经) / 1.25 秒(纬)
            lon += 5.0 / 1440.0 * (ord(g[6]) - 65) + 5.0 / 2880.0
            lat += 2.5 / 1440.0 * (ord(g[7]) - 65) + 2.5 / 2880.0

    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon < 180.0):
        raise GridError(f"网格超出地球范围: {grid!r}")
    return lat, lon
