#!/usr/bin/env bash
# RS44 FT4 多普勒自动跟踪 —— 启动脚本 (Linux/macOS)。
# 打开图形界面（方位角/高度角极坐标图），启动后不占用终端——脚本把窗口进程放到后台
# 就立刻退出，日志写到 /tmp/rs44-ft4-gui.log，终端可以马上挪去干别的事。
#
# 纯透传：所有配置都来自 config.toml（rs44-tracker 自己读取）或你手动传的参数，
# 脚本本身不内置任何默认值，避免脚本和 config.toml 出现数值不同步。
#
# 用法：
#   ./rs44-ft4.sh                          # 用 config.toml 打开窗口
#   ./rs44-ft4.sh --dry-run                # 不连接 flrig，仅显示计算结果
#   ./rs44-ft4.sh --latitude 30.94 --longitude 100.04   # 临时覆盖某一项
#
# 仍想要不开窗口、纯终端输出的旧行为：uv run rs44-tracker run ...
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv >/dev/null 2>&1; then
    echo "错误：未找到 uv，请先安装：https://docs.astral.sh/uv/" >&2
    exit 1
fi

if [ ! -f config.toml ]; then
    echo "[提示] 未找到 config.toml，将使用内置默认值；可 cp config.example.toml config.toml，"
    echo "       或通过命令行参数传入台站位置，例如 --latitude/--longitude。"
fi

echo "[rs44-ft4] 同步依赖..."
uv sync --quiet

LOG_FILE="/tmp/rs44-ft4-gui.log"
echo "[rs44-ft4] 启动图形界面..."
nohup uv run rs44-tracker gui "$@" > "$LOG_FILE" 2>&1 &
disown
echo "[rs44-ft4] 已在后台启动（PID $!），日志见 $LOG_FILE；关闭窗口即可结束跟踪。"
