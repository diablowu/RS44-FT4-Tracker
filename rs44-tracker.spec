# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：生成当前操作系统的单一可执行文件。

用法（由 build.sh / build.ps1 调用）：
    uv run --group build pyinstaller --clean --noconfirm rs44-tracker.spec

产物的文件名就是下面 EXE 的 name：Linux/macOS 为 dist/rs44-tracker，
Windows 为 dist\\rs44-tracker.exe。PyInstaller 不做交叉编译，在哪个系统上
执行构建，就得到哪个系统的可执行文件。
"""

import os
import sys
import sysconfig

from PyInstaller.utils.hooks import collect_data_files

# uv 使用的 python-build-standalone 在 Linux 上把 libtcl9.0.so / libtcl9tk9.0.so
# 放在 Python 的 LIBDIR 下，而该目录不在动态链接器的默认搜索路径里。PyInstaller
# 用 ldd 解析 _tkinter 的依赖时找不到这两个库，冻结后的 tkinter 会报
# "ImportError: libtcl9.0.so: cannot open shared object file"。在 Analysis 之前
# 把 LIBDIR 加进 LD_LIBRARY_PATH，让 ldd 能解析并随包收集（只影响构建进程）。
if sys.platform.startswith("linux"):
    _libdir = sysconfig.get_config_var("LIBDIR")
    if _libdir:
        _old_ld_path = os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = (
            _libdir + (os.pathsep + _old_ld_path if _old_ld_path else "")
        )

# skyfield 用 pkgutil.get_data 读取自带的 iers.npz / delta_t.npz 等数据文件，
# 必须随包带上，否则冻结后的程序在 load.timescale(builtin=True) 处会报错。
# pyinstaller-hooks-contrib 自带的 hook-skyfield 也会做同样的事，这里显式列出，
# 避免依赖 hook 版本。
datas = collect_data_files("skyfield")

a = Analysis(
    ["src/rs44_ft4_tracker/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="rs44-tracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
