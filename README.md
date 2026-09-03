# rs44-ft4-tracker

RS44（NORAD 44909）FT4 多普勒自动跟踪程序。通过 **flrig** 的 XML-RPC 接口实时重调
**ICOM IC-9700** 卫星模式的 **Main（下行）/ Sub（上行）** 两个波段，补偿卫星多普勒频移。

- 下行（Main）：435.612 MHz `USB-D`
- 上行（Sub）：145.993 MHz `LSB-D`

两个频率/模式均为默认值，可在 `config.toml` 中修改。

## 工作原理

1. 从 Celestrak 按 NORAD 编号 44909 下载 RS44 的 TLE（本地缓存，12 小时自动刷新，离线时回退用缓存）；
2. 用 skyfield/SGP4 计算卫星相对台站的径向速度 `rr`（正=远离）；
3. 按单向多普勒分别修正两条链路（线性转发器全双工的标准做法）：
   - 下行（收）：调谐频率 = `f·(1 − rr/c)`
   - 上行（发）：发射频率 = `f/(1 − rr/c)`
4. 每个周期把结果通过 flrig XML-RPC 写入电台：
   - `rig.set_vfoA()` → **Main** 波段（flrig 的 IC-9700 驱动中 VFO A=Main、B=Sub）
   - `rig.set_vfoB()` → **Sub** 波段
   - 模式用 `rig.set_modeA("USB-D")` / `rig.set_modeB("LSB-D")`（启动时设置一次）

IC-9700 支持 1 Hz 频率步进；默认逐 Hz 校正（`retune_threshold_hz`，可配置），且无论卫星
是否在地平线上都持续计算并写入电台。若连续多次连接 flrig 失败（默认 5 次），判定电台
离线，改为每 10 秒才重试一次，避免每个周期都卡在连接超时上（参考 gpredict 的错误计数
策略）；重新可达后自动恢复正常节奏。

## 安装

需要 [uv](https://docs.astral.sh/uv/)：

```bash
cd rs44-ft4-tracker
uv sync            # 创建虚拟环境并安装依赖（skyfield 等）
```

## 电台与 flrig 准备

1. IC-9700 开启**卫星模式**（SAT），Main=70cm 下行、Sub=2m 上行（默认约定，可在配置翻转）；
2. flrig 选择 IC-9700 并确认能正常控制电台；
3. flrig 打开 XML-RPC 服务：*Config → XmlRpc → Enable*（默认 `127.0.0.1:12345`）。

## 配置

```bash
cp config.example.toml config.toml
```

必填项只有台站位置（`[station]` 的 `locator` 或经纬度）。其余保持默认即可。
所有选项见 `config.example.toml` 内注释。

配置文件里的每一项也都有对应的命令行参数（`run`/`passes` 均支持，`uv run rs44-tracker run -h`
查看完整列表），命令行传了就覆盖配置文件/内置默认值，没传就保持原样——可以完全不用配置
文件，只用命令行跑：

```bash
uv run rs44-tracker run --dry-run --once --latitude 30.9375 --longitude 100.0417 \
    --downlink-mhz 435.612 --uplink-mhz 145.993
```

## 使用

```bash
# 查看未来 24 小时过境（先确认 TLE 能下载、台站位置正确）
uv run rs44-tracker passes

# 实时跟踪（启动时设置模式，过境期间持续校正，Ctrl-C 退出）
uv run rs44-tracker run

# 只算一次并打印（不碰电台）——检查配置/几何的好办法
uv run rs44-tracker run --dry-run --once

# 不连接电台的持续演示
uv run rs44-tracker run --dry-run

# 临时用 0.5 s 周期跟踪
uv run rs44-tracker run --interval 0.5

# 指定其他配置文件
uv run rs44-tracker run -c /path/to/config.toml

# 图形界面：方位角/高度角极坐标图，不占用终端输出（见下面“图形界面”一节）
uv run rs44-tracker gui
```

也可以用仓库根目录下的一键启动脚本（自动 `uv sync` + 在后台打开图形界面，参数原样转发，
脚本本身立刻退出，不占用控制台）：

```bash
./rs44-ft4.sh --dry-run      # Linux/macOS
```

```powershell
.\rs44-ft4.ps1 --dry-run     # Windows；若提示执行策略限制，先执行：
                              # Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

`passes` 输出示例（时间自动按系统时区显示，示例为 CST=UTC+8；系统未设置时区时显示 UTC）：

```
RS-44 (NORAD 44909) 未来过境  台站 30.9375, 100.0417  最低高度 0°
 #  AOS              LOS              峰值时刻          峰值EL     时长
 1  08-27 12:58:27   08-27 13:14:27   08-27 13:06:12     15.3°    16m00s
 2  08-27 14:48:57   08-27 15:09:27   08-27 14:58:42     70.5°    20m30s
```

`run` 运行时的状态行（单行刷新）：

```
05:52:19 CST EL-025.9° AZ359.6° RR-3.17km/s Δ↓+004604Hz Δ↑-001543Hz Main435.616604 Sub145.991457 [过境]
```

所有时间显示均取系统本地时区（读取 `TZ`/`/etc/localtime`），取不到时区信息则自动退化为 UTC；
轨道计算本身与显示时区无关。

地平线下时同样持续校正并写入电台（多普勒偏移量随几何变化，退出/重入过境时不必等待
频率追上），状态行改为显示下一圈 AOS 倒计时。

## 图形界面

```bash
uv run rs44-tracker gui              # 实时跟踪并连接 flrig
uv run rs44-tracker gui --dry-run    # 不连接电台，仅显示
```

`gui` 用 tkinter（标准库，无需额外依赖）打开一个窗口，启动后**不再往终端打印状态**，
和 `run` 共用同一套配置文件/命令行参数。窗口内容参考 gpredict 的 Polar View：

- 以地面站为圆心的方位角/高度角极坐标图：正北在上、方位角顺时针增大；圆心=天顶
  （El 90°），最外圈=地平线（El 0°），中间两圈是 El 60°/30°；
- 卫星进入过境窗口后，把整段过境（AOS→LOS）的方位角/高度角轨迹画成一条曲线，
  再用一个红点标出卫星当前位置（随刷新周期移动，地平线下时红点隐藏）；
- 右侧面板显示时间、方位角/高度角、斜距、径向速度、下行/上行多普勒偏移、
  Main/Sub 调谐频率、过境状态、下次入境倒计时（过境中则显示到 LOS 的倒计时）、
  电台连接状态、当前预设。

关闭窗口即结束跟踪；命令行参数解析、退避重连等逻辑与 `run` 完全一致。

### 预设频率

`radio.preset_freq_pairs` 可以配多组常用的下行/上行频率对（比如同一转发器的不同
FT4 频率），每组格式是 `"下行;上行"`（MHz）：

```toml
[radio]
preset_freq_pairs = ["435.611000;145.990150", "435.610000;145.991000"]
```

命令行等价写法（`--preset-freq-pair` 可重复传多组）：

```bash
uv run rs44-tracker gui \
    --preset-freq-pair 435.611000;145.990150 \
    --preset-freq-pair 435.610000;145.991000
```

配置/命令行里有预设列表时，`gui` 窗口会在下方多出一排预设按钮，点击即把当前
downlink/uplink 标称频率切换过去，并在按钮下方的状态栏提示切换结果；当前生效的
预设也会同步显示在右侧信息面板的“预设”一行。

**注意**：如果是通过命令行 `--preset-freq-pair` 传的（不是只写在 config.toml 里），
程序启动时会直接把第 1 组当作本次运行的 downlink/uplink 标称频率使用。

## 开发

```bash
uv run pytest       # 单元测试（网格换算、多普勒符号约定、mock flrig 服务端等）
```

`tools/civ_sim.py` 是一个 IC-9700 CI-V 协议模拟器（伪终端），可在没有真实电台的情况下
用真实 flrig 二进制做端到端调试：

```bash
uv run python tools/civ_sim.py   # 打印分配到的从端路径，如 /dev/pts/5
# 把该路径填入 flrig 的 IC-9700.prefs -> xcvr_serial_port，选 IC-9700 后启动 flrig
```

源码结构：

| 文件 | 职责 |
| --- | --- |
| `src/rs44_ft4_tracker/config.py` | TOML 配置加载与默认值 |
| `src/rs44_ft4_tracker/maidenhead.py` | 网格坐标 → 经纬度 |
| `src/rs44_ft4_tracker/doppler.py` | TLE 获取/缓存、卫星几何、多普勒公式、过境预测 |
| `src/rs44_ft4_tracker/flrig.py` | flrig XML-RPC 客户端（VFO A=Main / B=Sub） |
| `src/rs44_ft4_tracker/tracker.py` | 主循环：AOS/LOS、阈值重调、状态显示 |
| `src/rs44_ft4_tracker/gui.py` | tkinter 图形界面（方位角/高度角极坐标图） |
| `src/rs44_ft4_tracker/cli.py` | 命令行入口（`run`/`gui`/`passes`） |

## 注意事项

- **TLE 时效**：TLE 过期后多普勒计算误差增大；程序每 12 小时自动刷新（可改
  `satellite.tle_max_age_h`），也可用 `satellite.tle_file` 完全离线。
- **FT4 频率**：435.612/145.993 是 RS44 转发器上常用的 FT4 频率对（反转式转发器）。
  若按其他资料调整，成对修改 `[radio]` 即可。
- **退出行为**：Ctrl-C 退出时电台保持当时的频率，不会自动回中；下次过境开始时会
  重新强制写入正确频率。
- **过境期间**程序只改频率，不改 PTT/功率等其他设置。
- 若 flrig 中电台不是 IC-9700，程序会警告（VFO A/B 与 Main/Sub 的映射只在 IC-9700
  卫星模式下成立）。
