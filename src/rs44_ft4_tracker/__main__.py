"""`python -m rs44_ft4_tracker` 入口，同时也是 PyInstaller 打包时的单一入口脚本。

打包后的可执行文件与 `uv run rs44-tracker` 行为完全一致（`run`/`gui`/`passes`）。
"""

from __future__ import annotations

import sys

from rs44_ft4_tracker.cli import main

if __name__ == "__main__":
    sys.exit(main())
