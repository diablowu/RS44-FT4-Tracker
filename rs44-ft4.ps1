# RS44 FT4 多普勒自动跟踪 —— 启动脚本 (Windows/PowerShell)。
# 打开图形界面（方位角/高度角极坐标图），启动后不占用控制台——脚本把窗口进程放到
# 后台就立刻退出，日志写到 $env:TEMP\rs44-ft4-gui.log，控制台可以马上挪去干别的事。
#
# 纯透传：所有配置都来自 config.toml（rs44-tracker 自己读取）或你手动传的参数，
# 脚本本身不内置任何默认值，避免脚本和 config.toml 出现数值不同步。
#
# 用法：
#   .\rs44-ft4.ps1                          # 用 config.toml 打开窗口
#   .\rs44-ft4.ps1 --dry-run                # 不连接 flrig，仅显示计算结果
#   .\rs44-ft4.ps1 --latitude 30.94 --longitude 100.04   # 临时覆盖某一项
#
# 仍想要不开窗口、纯终端输出的旧行为：uv run rs44-tracker run ...

$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 uv，请先安装：https://docs.astral.sh/uv/"
    exit 1
}

if (-not (Test-Path "config.toml")) {
    Write-Host "[提示] 未找到 config.toml，将使用内置默认值；可复制 config.example.toml 为 config.toml，"
    Write-Host "       或通过命令行参数传入台站位置，例如 --latitude/--longitude。"
}

Write-Host "[rs44-ft4] 同步依赖..."
uv sync --quiet
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$OutLog = Join-Path $env:TEMP "rs44-ft4-gui.log"
$ErrLog = Join-Path $env:TEMP "rs44-ft4-gui.err.log"
Write-Host "[rs44-ft4] 启动图形界面..."
$AllArgs = @("run", "rs44-tracker", "gui") + $args
$proc = Start-Process -FilePath "uv" -ArgumentList $AllArgs `
    -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog `
    -WindowStyle Hidden -PassThru
Write-Host "[rs44-ft4] 已在后台启动（PID $($proc.Id)），日志见 $OutLog；关闭窗口即可结束跟踪。"
