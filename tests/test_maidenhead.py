"""Maidenhead 网格转换测试。"""

import pytest

from rs44_ft4_tracker.maidenhead import GridError, grid_to_latlon


@pytest.mark.parametrize(
    ("grid", "lat", "lon"),
    [
        # 手算对照: 纬 = -90+10*字段+1*方格+2.5'*子格(中心+1.25')
        #           经 = -180+20*字段+2*方格+5'*子格(中心+2.5')
        ("JO65XA", 55.020833, 13.958333),
        ("JO65", 55.5, 13.0),
        ("OM00aw", 30.9375, 100.041667),   # ~川西/滇北
        ("FN31pr", 41.729167, -72.708333),  # ARRL 总部所在网格
        ("jo65xa", 55.020833, 13.958333),   # 大小写不敏感
    ],
)
def test_grid_centers(grid, lat, lon):
    got_lat, got_lon = grid_to_latlon(grid)
    assert got_lat == pytest.approx(lat, abs=1e-4)
    assert got_lon == pytest.approx(lon, abs=1e-4)


@pytest.mark.parametrize(
    "grid", ["", "A", "JO65X", "JO65XA56X", "XZ65XA", "Jx65XA", "JOa5XA", "JJ-5XA"]
)
def test_invalid_grid(grid):
    with pytest.raises(GridError):
        grid_to_latlon(grid)
