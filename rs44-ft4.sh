#!/usr/bin/env bash
# RS44 FT4 多普勒自动跟踪 —— 启动脚本 (Linux/macOS)。
#
# 用法：
#   ./rs44-ft4.sh                          # 用 config.toml 实时跟踪
#   ./rs44-ft4.sh --dry-run --once         # 只算一次并打印，不碰电台
#   ./rs44-ft4.sh --latitude 30.94 --longitude 100.04   # 不用配置文件，直接传台站位置
#
# 所有参数原样转给 `rs44-tracker run`（见 `uv run rs44-tracker run -h`）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv >/dev/null 2>&1; then
    echo "错误：未找到 uv，请先安装：https://docs.astral.sh/uv/" >&2
    exit 1
fi

if [ ! -f config.toml ] && [ ! -f config.example.toml ]; then
    echo "错误：未找到 config.toml/config.example.toml，请确认脚本位于项目根目录" >&2
    exit 1
fi

if [ ! -f config.toml ]; then
    echo "[提示] 未找到 config.toml，将使用内置默认值；可 cp config.example.toml config.toml，"
    echo "       或通过命令行参数传入台站位置，例如 --latitude/--longitude。"
fi

echo "[rs44-ft4] 同步依赖..."
uv sync --quiet

echo "[rs44-ft4] 启动跟踪（Ctrl-C 退出）..."
exec uv run rs44-tracker run "$@"
