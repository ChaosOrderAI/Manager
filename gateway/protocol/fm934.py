"""FM934 vendor extension parsing (附录D 上行扩展指令).

Extension commands arrive inside location-message extra item 0x30
(兼容2929扩展协议) or as standalone uplink commands. Format:
    WORD length (includes 2-byte cmd + data) | WORD cmd | data
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Optional

# command ids
CMD_ICCID = 0x00B2
CMD_ALARM_STATE = 0x0089       # extended alarm bits (bit12 拆除报警)
CMD_LBS_4G = 0x00D8            # 4G base station info
CMD_ALARM_STATE2 = 0x00C5      # positioning mode / vibration / light
CMD_EXT_VOLTAGE = 0x002D       # external voltage mV
CMD_BATTERY_PCT = 0x00A8
CMD_IMEI = 0x00D5
CMD_WIFI = 0x00B9
CMD_MODE_UPLOAD = 0x002A       # working mode + report interval
CMD_PRODUCT_ID = 0x00A3        # FM934 product/firmware serial string

MODES = {0: "追踪模式", 1: "点名模式", 2: "定时模式",
         3: "强跟踪模式", 4: "临时追踪", 5: "定时飞行模式"}


@dataclass
class LbsInfo:
    mcc: int
    mnc: int
    lac: int
    cell_id: int


@dataclass
class WifiItem:
    mac: str
    rssi: int


@dataclass
class ExtData:
    iccid: Optional[str] = None
    imei: Optional[str] = None
    alarm_state: Optional[int] = None      # 0x0089 raw
    alarm_state2: Optional[int] = None     # 0x00C5 raw
    lbs: Optional[LbsInfo] = None
    ext_voltage_mv: Optional[int] = None
    battery_pct: Optional[int] = None
    wifi: list[WifiItem] = field(default_factory=list)
    work_mode: Optional[int] = None
    report_interval: Optional[int] = None  # seconds
    product_id: Optional[str] = None       # 0x00A3 e.g. "RM68SFM934FJTS10403D261027"

    @property
    def detached_alarm(self) -> Optional[bool]:
        """0x0089 bit12: 0=报警 1=正常."""
        if self.alarm_state is None:
            return None
        return not bool(self.alarm_state & (1 << 12))

    @property
    def vibrate_alarm(self) -> Optional[bool]:
        """0x00C5 bit6: 1 正常 0 振动报警."""
        if self.alarm_state2 is None:
            return None
        return not bool(self.alarm_state2 & (1 << 6))


def parse_ext_payload(data: bytes) -> ExtData:
    """Parse a concatenated sequence of extension commands."""
    ext = ExtData()
    i = 0
    while i + 4 <= len(data):
        length, cmd = struct.unpack(">HH", data[i:i + 4])
        body = data[i + 4: i + 2 + length]  # length covers cmd+data
        i += 2 + length
        _dispatch(ext, cmd, body)
    return ext


def _dispatch(ext: ExtData, cmd: int, d: bytes) -> None:
    if cmd == CMD_ICCID:
        ext.iccid = d[:10].hex().upper()
    elif cmd == CMD_IMEI:
        # spec: 15 bytes of ASCII hex chars ("383633..." -> "86307...")
        try:
            ext.imei = bytes.fromhex(d.decode("ascii").strip())
        except (ValueError, UnicodeDecodeError):
            ext.imei = d.decode("ascii", errors="replace").strip("\x00 ")
    elif cmd == CMD_ALARM_STATE:
        if len(d) >= 4:
            ext.alarm_state = struct.unpack(">I", d[:4])[0]
    elif cmd == CMD_ALARM_STATE2:
        if len(d) >= 4:
            ext.alarm_state2 = struct.unpack(">I", d[:4])[0]
    elif cmd == CMD_EXT_VOLTAGE:
        if len(d) >= 2:
            ext.ext_voltage_mv = struct.unpack(">H", d[:2])[0]
    elif cmd == CMD_BATTERY_PCT:
        if d:
            ext.battery_pct = d[0]
    elif cmd == CMD_LBS_4G:
        if len(d) >= 9:
            mcc, mnc, lac, cell = struct.unpack(">HBHI", d[:9])
            ext.lbs = LbsInfo(mcc, mnc, lac, cell)
    elif cmd == CMD_WIFI:
        if d:
            n = d[0]
            text = d[1:].decode("ascii", errors="replace")
            parts = text.split(",")
            # MAC 必含 ':',信号值 '-30' 不会误判
            macs = []
            for j, p in enumerate(parts):
                if ":" in p:
                    rssi = 0
                    if j + 1 < len(parts):
                        try:
                            rssi = int(parts[j + 1])
                        except ValueError:
                            pass
                    macs.append(WifiItem(p.strip(), rssi))
            ext.wifi = macs[:n] if n else macs
    elif cmd == CMD_MODE_UPLOAD:
        if len(d) >= 5:
            ext.work_mode = d[0]
            ext.report_interval = struct.unpack(">I", d[1:5])[0]
    elif cmd == CMD_PRODUCT_ID:
        ext.product_id = d.decode("ascii", errors="replace").strip("\x00 ")
