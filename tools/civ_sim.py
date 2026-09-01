"""IC-9700 CI-V 协议模拟器：在一个伪终端(PTY)上模拟电台，供真实 flrig 二进制连接。

用于不依赖真实硬件、对 rs44-tracker 做端到端调试/回归测试：flrig 把这个 PTY 的
从端当作串口打开，本脚本在主端解析/回应标准 ICOM CI-V 帧。协议细节（03/05 读写
频率、04/06 读写模式、07 D0/D1 选 Main/Sub 波段、1A 06 数据模式标志、16 5A/16 59
卫星模式与双watch 查询、BCD 频率编码）均对照真实 flrig 2.0.12 源码
（src/rigs/icom/IC9700.cxx）验证过，尤其是 16 5A/16 59：必须回复
`FE FE <ctrl> <radio> 16 <subcmd> <value> FD`，回一个裸 FB 会导致 flrig 的
get_sat_mode() 越界读取、后续初始化直接被跳过（XML-RPC 一直返回默认值/空值）。

用法：
    uv run python tools/civ_sim.py
    # 第一行 stdout 会打印分配到的从端路径，例如 /dev/pts/5

    把该路径写入 flrig 的 IC-9700.prefs 的 xcvr_serial_port，
    选择 IC-9700 电台类型后启动 flrig 即可对接。
"""

from __future__ import annotations

import os
import pty
import sys
import tty

FE = 0xFE
FD = 0xFD
CTRL_ADDR = 0xE0     # flrig 默认控制器地址
RADIO_ADDR = 0xA2    # IC-9700 默认 CI-V 地址

MODE_CODE = {"LSB": 0x00, "USB": 0x01, "AM": 0x02, "CW": 0x03, "FM": 0x05, "CW-R": 0x07}
CODE_MODE = {v: k for k, v in MODE_CODE.items()}

state = {
    "A": {"freq": 435_612_000, "mode": "USB", "data": False},
    "B": {"freq": 145_993_000, "mode": "LSB", "data": False},
    "selected": "A",  # 07 D0 -> A(Main), 07 D1 -> B(Sub)
}


def log(msg: str) -> None:
    print(f"[civ-sim] {msg}", file=sys.stderr, flush=True)


def freq_to_bcd(freq_hz: int) -> bytes:
    s = f"{int(freq_hz):010d}"
    pairs = [s[i:i + 2] for i in range(0, 10, 2)]
    return bytes(int(p, 16) for p in reversed(pairs))


def bcd_to_freq(data: bytes) -> int:
    pairs = [f"{b:02x}" for b in reversed(data)]
    return int("".join(pairs))


def reply_frame(fd: int, cmd: int, payload: bytes = b"") -> None:
    frame = bytes([FE, FE, CTRL_ADDR, RADIO_ADDR, cmd]) + payload + bytes([FD])
    log(f"-> {frame.hex()}")
    os.write(fd, frame)


def ack(fd: int, ok: bool = True) -> None:
    reply_frame(fd, 0xFB if ok else 0xFA)


def selected() -> dict:
    return state[state["selected"]]


def handle_frame(fd: int, to: int, body: bytes) -> None:
    if to not in (RADIO_ADDR, 0x00):
        return  # 不是发给这台电台的
    if not body:
        return
    cmd = body[0]
    data = body[1:]

    if cmd == 0x03:  # 读当前选中波段频率
        reply_frame(fd, 0x03, freq_to_bcd(selected()["freq"]))
    elif cmd == 0x05:  # 写当前选中波段频率
        selected()["freq"] = bcd_to_freq(data)
        ack(fd)
    elif cmd == 0x04:  # 读当前选中波段模式
        code = MODE_CODE.get(selected()["mode"], 0x01)
        reply_frame(fd, 0x04, bytes([code, 0x01]))
    elif cmd == 0x06:  # 写当前选中波段模式
        if data:
            selected()["mode"] = CODE_MODE.get(data[0], selected()["mode"])
        ack(fd)
    elif cmd == 0x07:  # 选择 Main(D0)/Sub(D1) 波段
        if data == b"\xd0":
            state["selected"] = "A"
            ack(fd)
        elif data == b"\xd1":
            state["selected"] = "B"
            ack(fd)
        else:
            ack(fd, ok=False)
    elif cmd == 0x19 and data == b"\x00":  # 读电台 CI-V 地址
        reply_frame(fd, 0x19, bytes([0x00, RADIO_ADDR]))
    elif cmd == 0x1A and data[:1] == b"\x06":  # 数据模式标志
        if len(data) >= 2:  # 写：1A 06 <0/1>
            selected()["data"] = bool(data[1])
            ack(fd)
        else:  # 读：1A 06
            reply_frame(fd, 0x1A, bytes([0x06, 1 if selected()["data"] else 0]))
    elif cmd == 0x1C:  # PTT 读/写，测试中不用，回默认值
        if len(data) >= 2:
            ack(fd)
        else:
            reply_frame(fd, 0x1C, bytes([0x00, 0x00]))
    elif cmd == 0x16 and len(data) == 1:  # 16 5A/16 59 等：只带 subcmd 就是查询
        sub = data[0]
        val = 1 if sub == 0x5A else 0  # 0x5A=卫星模式(常开，匹配 IC-9700 卫星用法)；其余(如 0x59 双watch)默认关
        reply_frame(fd, 0x16, bytes([sub, val]))
    elif cmd == 0x16:  # 带值字节 => 设置命令
        ack(fd)
    else:
        ack(fd)  # 未知命令：给个 OK，避免 flrig 轮询线程卡死等待


def main() -> None:
    master_fd, secondary_fd = pty.openpty()
    tty.setraw(secondary_fd)
    port = os.ttyname(secondary_fd)
    # 不关闭 secondary_fd：Linux 下若从端一个 fd 都没打开过，读主端会立刻 EIO。
    # 保留这个引用不用，只是让 pty 在 flrig 打开它自己的 fd 之前也一直"活着"。
    print(port, flush=True)  # 第一行输出从端路径，供调用方捕获
    log(f"secondary pty: {port}")

    buf = bytearray()
    while True:
        chunk = os.read(master_fd, 4096)
        if not chunk:
            break
        buf.extend(chunk)
        while True:
            start = buf.find(bytes([FE, FE]))
            if start < 0:
                buf.clear()
                break
            end = buf.find(bytes([FD]), start)
            if end < 0:
                del buf[:start]
                break
            frame = bytes(buf[start:end + 1])
            del buf[:end + 1]
            log(f"<- {frame.hex()}")
            # frame: FE FE <to> <from> <body...> FD
            if len(frame) < 5:
                continue
            to = frame[2]
            body = frame[4:-1]
            try:
                handle_frame(master_fd, to, body)
            except Exception as exc:  # noqa: BLE001 - 模拟器不能因单帧解析异常退出
                log(f"error handling frame {frame.hex()}: {exc}")


if __name__ == "__main__":
    main()
