"""flrig XML-RPC 客户端（针对 IC-9700 卫星模式）。

IC-9700 卫星模式下 flrig 的映射（flrig 源码 IC9700.cxx, DUALWATCH_SUB_AS_B）：
  - VFO A = Main 波段（CI-V 地址 A2）
  - VFO B = Sub  波段（CI-V 地址 A3）
  - 模式名: LSB/USB/AM/FM/DV/CW/CW-R/RTTY/RTTY-R/LSB-D/USB-D/AM-D/FM-D/DV-R
  - 频率单位 Hz，精度 1 Hz；get_vfoA/get_vfoB 返回的是数字字符串
"""

from __future__ import annotations

import http.client
import xmlrpc.client
from typing import Literal

VFO = Literal["A", "B"]

_MODES = {
    "LSB", "USB", "AM", "FM", "DV", "CW", "CW-R", "RTTY", "RTTY-R",
    "LSB-D", "USB-D", "AM-D", "FM-D", "DV-R",
}


class _TimeoutTransport(xmlrpc.client.Transport):
    """带连接/读取超时的 Transport（flrig 卡死时不至于挂住整个程序）。"""

    def __init__(self, timeout: float) -> None:
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        host, _headers, _x509 = self.get_host_info(host)
        return http.client.HTTPConnection(host, timeout=self._timeout)


class FlrigError(RuntimeError):
    """与 flrig 通信失败（不在线、方法不存在、超时等）。"""


class FlrigClient:
    """flrig XML-RPC 封装。所有方法失败时抛 FlrigError。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 12345, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self._proxy = xmlrpc.client.ServerProxy(
            f"http://{host}:{port}/", transport=_TimeoutTransport(timeout), allow_none=True
        )

    # ------------------------------------------------------------------ 基础
    def _call(self, name: str, *args):
        try:
            fn = self._proxy
            for part in name.split("."):
                fn = getattr(fn, part)
            return fn(*args)
        except xmlrpc.client.Fault as exc:
            raise FlrigError(f"flrig 方法 {name} 调用失败: {exc.faultString}") from exc
        except (xmlrpc.client.ProtocolError, OSError, http.client.HTTPException) as exc:
            raise FlrigError(f"无法连接 flrig ({self.host}:{self.port}): {exc}") from exc

    def ping(self) -> str:
        """返回 flrig 版本号，用于连通性测试。"""
        return str(self._call("main.get_version"))

    def get_xcvr(self) -> str:
        """返回 flrig 当前控制的电台型号名，如 'IC-9700'。"""
        return str(self._call("rig.get_xcvr"))

    # ------------------------------------------------------------------ 频率
    def get_frequency(self, vfo: VFO) -> int:
        """读取 Main(A)/Sub(B) 频率，单位 Hz。"""
        raw = self._call(f"rig.get_vfo{vfo}")
        return int(float(raw))  # flrig 返回字符串形式的 Hz

    def set_frequency(self, vfo: VFO, freq_hz: float) -> None:
        """设置 Main(A)/Sub(B) 频率，单位 Hz（IC-9700 支持 1 Hz 步进）。"""
        self._call(f"rig.set_vfo{vfo}", float(freq_hz))

    # ------------------------------------------------------------------ 模式
    def get_mode(self, vfo: VFO) -> str:
        """读取 Main(A)/Sub(B) 模式。

        实测 flrig 2.0.12 的 IC-9700 驱动里 get_modeB／set_modeB 都不会像
        get_vfoB／set_vfoB 那样先切到 Sub 波段——直接对"当前选中的波段"下发
        CI-V 命令；若此时 Main 仍被选中，读到的其实是 Main 的模式。用
        rig.set_AB 显式切到目标波段再读/写、操作 Sub 后切回 Main，规避这个
        问题（该行为已用真实 flrig 二进制 + CI-V 模拟器验证）。
        """
        if vfo == "B":
            self._call("rig.set_AB", "B")
        try:
            return str(self._call(f"rig.get_mode{vfo}"))
        finally:
            if vfo == "B":
                self._call("rig.set_AB", "A")

    def set_mode(self, vfo: VFO, mode: str) -> bool:
        """设置模式；返回是否成功（未知模式名返回 False）。见 get_mode 的说明。"""
        if vfo == "B":
            self._call("rig.set_AB", "B")
        try:
            ok = self._call(f"rig.set_mode{vfo}", mode)
        finally:
            if vfo == "B":
                self._call("rig.set_AB", "A")
        return bool(int(ok))

    # ------------------------------------------------------------------ 组合
    def setup_sat_pair(
        self,
        main_hz: float,
        main_mode: str,
        sub_hz: float,
        sub_mode: str,
        set_mode: bool = True,
    ) -> None:
        """初始配置：Main 频率/模式 + Sub 频率/模式。"""
        if set_mode:
            for vfo, mode in (("A", main_mode), ("B", sub_mode)):
                if not self.set_mode(vfo, mode):
                    known = ", ".join(sorted(_MODES))
                    raise FlrigError(
                        f"设置 VFO {vfo} 模式 {mode!r} 失败（IC-9700 可用模式: {known}）"
                    )
        self.set_frequency("A", main_hz)
        self.set_frequency("B", sub_hz)
