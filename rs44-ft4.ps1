# RS44 FT4 多普勒自动跟踪 —— 启动脚本 (Windows/PowerShell)。
#
# 用法：
#   .\rs44-ft4.ps1                          # 用 config.toml 实时跟踪
#   .\rs44-ft4.ps1 --dry-run --once         # 只算一次并打印，不碰电台
#   .\rs44-ft4.ps1 --latitude 30.94 --longitude 100.04   # 不用配置文件，直接传台站位置
#
# 所有参数原样转给 `rs44-tracker run`（见 `uv run rs44-tracker run -h`）。

$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 uv，请先安装：https://docs.astral.sh/uv/"
    exit 1
}

if (-not (Test-Path "config.toml") -and -not (Test-Path "config.example.toml")) {
    Write-Error "未找到 config.toml/config.example.toml，请确认脚本位于项目根目录"
    exit 1
}

if (-not (Test-Path "config.toml")) {
    Write-Host "[提示] 未找到 config.toml，将使用内置默认值；可复制 config.example.toml 为 config.toml，"
    Write-Host "       或通过命令行参数传入台站位置，例如 --latitude/--longitude。"
}

Write-Host "[rs44-ft4] 同步依赖..."
uv sync --quiet
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[rs44-ft4] 启动跟踪（Ctrl-C 退出）..."
uv run rs44-tracker run @args
exit $LASTEXITCODE
