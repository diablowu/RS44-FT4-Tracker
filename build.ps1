# RS44 FT4 多普勒自动跟踪 —— 构建脚本 (Windows/PowerShell)。
# 用 PyInstaller 把程序（含 skyfield/numpy/tkinter 依赖）打包成一个可执行文件，
# 目标机器无需再安装 Python 或 uv。
#
# 生成什么系统的东西取决于在哪个系统上运行：Windows 上得到 .exe，Linux/macOS
# 请用同目录下的 build.sh（PyInstaller 不支持交叉编译）。
#
# 用法：
#   .\build.ps1
# 若提示执行策略限制，先执行：
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#
# 产物：dist\rs44-tracker.exe
#   .\dist\rs44-tracker.exe gui       # 图形界面
#   .\dist\rs44-tracker.exe passes    # 列出未来过境

$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 uv，请先安装：https://docs.astral.sh/uv/"
    exit 1
}

Write-Host "[rs44-ft4] 安装构建依赖..."
uv sync --group build --quiet
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[rs44-ft4] 正在打包成单一可执行文件（首次构建需要几分钟）..."
uv run --group build pyinstaller --clean --noconfirm rs44-tracker.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[rs44-ft4] 构建完成：$PSScriptRoot\dist\rs44-tracker.exe"
Write-Host "[rs44-ft4] 运行示例：$PSScriptRoot\dist\rs44-tracker.exe gui --dry-run"
