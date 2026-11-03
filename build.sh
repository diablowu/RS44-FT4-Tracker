#!/usr/bin/env bash
# RS44 FT4 多普勒自动跟踪 —— 构建脚本 (Linux/macOS)。
# 用 PyInstaller 把程序（含 skyfield/numpy/tkinter 依赖）打包成一个可执行文件，
# 目标机器无需再安装 Python 或 uv。
#
# 生成什么系统的东西取决于在哪个系统上运行：Linux 上得到 Linux 可执行文件，
# macOS 上得到 macOS 可执行文件（PyInstaller 不支持交叉编译）。Windows 请用
# 同目录下的 build.ps1。
#
# 用法：
#   ./build.sh
#
# 产物：dist/rs44-tracker
#   ./dist/rs44-tracker gui       # 图形界面
#   ./dist/rs44-tracker passes    # 列出未来过境
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv >/dev/null 2>&1; then
    echo "错误：未找到 uv，请先安装：https://docs.astral.sh/uv/" >&2
    exit 1
fi

echo "[rs44-ft4] 安装构建依赖..."
uv sync --group build --quiet

echo "[rs44-ft4] 正在打包成单一可执行文件（首次构建需要几分钟）..."
uv run --group build pyinstaller --clean --noconfirm rs44-tracker.spec

echo "[rs44-ft4] 构建完成：$SCRIPT_DIR/dist/rs44-tracker"
echo "[rs44-ft4] 运行示例：$SCRIPT_DIR/dist/rs44-tracker gui --dry-run"
