#!/usr/bin/env bash
# RS44 FT4 多普勒自动跟踪 —— 启动脚本 (Linux/macOS)。
#
# 用法：
#   ./rs44-ft4.sh                          # 用下面 DEFAULT_ARGS（快照自 config.toml）实时跟踪
#   ./rs44-ft4.sh --dry-run --once         # 只算一次并打印，不碰电台
#   ./rs44-ft4.sh --latitude 30.94 --longitude 100.04   # 临时覆盖某一项
#
# DEFAULT_ARGS 是 config.toml 里各项的快照，脚本本身已不依赖 config.toml 是否存在。
# 命令行传入的同名参数以命令行为准（排在 DEFAULT_ARGS 之后，后出现的覆盖先出现的）。
# 改了 config.toml 想同步到这里，需要手动更新下面这份列表。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DEFAULT_ARGS=(
    --locator OM89fv
    --flrig-host 127.0.0.1
    --flrig-port 12345
    --flrig-timeout 5.0
    --sat-name "RS-44"
    --norad-id 44909
    --tle-url "https://celestrak.org/NORAD/elements/gp.php?CATNR=44909&FORMAT=TLE"
    --tle-max-age 12.0
    --downlink-mhz 435.612
    --downlink-mode USB-D
    --uplink-mhz 145.99015
    --uplink-mode LSB-D
    --set-mode-on-start
    --main-band downlink
    --interval 1.0
    --min-elevation 0.0
    --retune-threshold 1.0
    --correct-downlink
    --correct-uplink
)

if ! command -v uv >/dev/null 2>&1; then
    echo "错误：未找到 uv，请先安装：https://docs.astral.sh/uv/" >&2
    exit 1
fi

echo "[rs44-ft4] 同步依赖..."
uv sync --quiet

echo "[rs44-ft4] 启动跟踪（Ctrl-C 退出）..."
exec uv run rs44-tracker run "${DEFAULT_ARGS[@]}" "$@"
