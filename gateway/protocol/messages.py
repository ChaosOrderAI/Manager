"""JT/T 808 message body builders & parsers for the FM934 dialect."""
from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .codec import Header, Message


def bcd_time(b: bytes) -> Optional[datetime]:
    """BCD[6] YY-MM-DD-hh-mm-ss."""
    if len(b) < 6:
        return None
    d = [int(f"{x >> 4}{x & 0x0F}") for x in b[:6]]
    try:
        return datetime(2000 + d[0], d[1], d[2], d[3], d[4], d[5])
    except ValueError:
        return None


def gbk(b: bytes) -> str:
    return b.split(b"\x00")[0].decode("gbk", errors="replace").strip()


# ---------------- terminal -> platform parsers ----------------

@dataclass
class CommonReply:
    reply_serial: int
    reply_id: int
    result: int  # 0 ok 1 fail 2 bad-msg 3 unsupported


def parse_0001(body: bytes) -> CommonReply:
    rs, rid, res = struct.unpack(">HHB", body[:5])
    return CommonReply(rs, rid, res)


@dataclass
class Register:
    province: int
    city: int
    manufacturer: str
    model: str
    terminal_id: str
    plate_color: int
    plate: str  # plate no., or VIN when plate_color == 0


def parse_0100(body: bytes) -> Register:
    """Register body. FM934 errata says model=20B; standard JT/T 808
    table says 8B. Try 20B first; if terminal_id decodes to something
    implausible (empty or all '0'), retry with 8B model."""
    province, city = struct.unpack(">HH", body[:4])
    manufacturer = body[4:9].decode("ascii", errors="replace")
    rest = body[9:]

    for model_len in (20, 8):
        if len(rest) < model_len + 8:
            continue
        model = rest[:model_len].split(b"\x00")[0].decode(
            "ascii", errors="replace").strip()
        tid_start = 9 + model_len
        terminal_id = body[tid_start:tid_start + 7].split(b"\x00")[0].decode(
            "ascii", errors="replace")
        # implausible tid -> wrong layout, try the other
        if terminal_id and terminal_id != "0" * len(terminal_id):
            plate_color = body[tid_start + 7] if len(body) > tid_start + 7 else 0
            plate = gbk(body[tid_start + 8:]) if len(body) > tid_start + 8 else ""
            return Register(province, city, manufacturer, model,
                            terminal_id, plate_color, plate)
    # couldn't parse a sane tid; return best-effort with 20B layout
    tid_start = 29
    return Register(province, city, manufacturer,
                    rest[:20].split(b"\x00")[0].decode("ascii", "replace").strip(),
                    "", body[36] if len(body) > 36 else 0,
                    gbk(body[37:]) if len(body) > 37 else "")


def parse_0102(body: bytes) -> str:
    """Auth code."""
    return gbk(body)


@dataclass
class Location:
    alarm: int           # DWORD alarm bits
    status: int          # DWORD status bits
    lat: float
    lng: float
    altitude: int        # m
    speed: float         # km/h (raw 1/10)
    direction: int       # 0-359
    time: Optional[datetime]
    extras: dict         # additional info items by id

    # decoded status helpers
    @property
    def acc_on(self) -> bool: return bool(self.status & 0x01)
    @property
    def positioned(self) -> bool: return bool(self.status & 0x02)
    @property
    def south(self) -> bool: return bool(self.status & 0x04)
    @property
    def west(self) -> bool: return bool(self.status & 0x08)
    @property
    def charging_disconnected(self) -> bool: return bool(self.status & (1 << 11))
    @property
    def beidou_only(self) -> bool: return bool(self.status & (1 << 19))


def _parse_extras(data: bytes) -> dict:
    extras: dict[int, list[bytes]] = {}
    i = 0
    while i + 2 <= len(data):
        eid, elen = data[i], data[i + 1]
        val = data[i + 2:i + 2 + elen]
        extras.setdefault(eid, []).append(val)
        i += 2 + elen
    return extras


def parse_0200(body: bytes) -> Location:
    alarm, status = struct.unpack(">II", body[:8])
    lat_raw, lng_raw = struct.unpack(">II", body[8:16])
    alt, spd, direction = struct.unpack(">HHH", body[16:22])
    t = bcd_time(body[22:28])
    extras = _parse_extras(body[28:]) if len(body) > 28 else {}
    loc = Location(alarm, status, lat_raw / 1e6, lng_raw / 1e6,
                   alt, spd / 10.0, direction, t, extras)
    if loc.south:
        loc.lat = -loc.lat
    if loc.west:
        loc.lng = -loc.lng
    return loc


@dataclass
class LocationQueryReply:
    reply_serial: int
    location: Location


def parse_0201(body: bytes) -> LocationQueryReply:
    rs = struct.unpack(">H", body[:2])[0]
    return LocationQueryReply(rs, parse_0200(body[2:]))


def parse_0104(body: bytes) -> tuple[int, list[tuple[int, bytes]]]:
    """Query-params reply: (reply_serial, [(param_id, value_bytes)])."""
    rs, count = body[0:2] and struct.unpack(">HB", body[:3]) or (0, 0)
    items: list[tuple[int, bytes]] = []
    i = 3
    for _ in range(count):
        pid, plen = struct.unpack(">IB", body[i:i + 5])
        items.append((pid, body[i + 5:i + 5 + plen]))
        i += 5 + plen
    return rs, items


def parse_6006(body: bytes) -> tuple[int, str]:
    """Text message upload: (encoding, text). 0=GB2312 1=UNICODE."""
    enc = body[0]
    raw = body[1:]
    text = raw.decode("utf-16-be", errors="replace") if enc == 1 else gbk(raw)
    return enc, text


# ---------------- platform -> terminal builders ----------------

def build_8001(reply_serial: int, reply_id: int, result: int, phone: str,
               serial: int) -> Message:
    body = struct.pack(">HHB", reply_serial, reply_id, result)
    h = Header(0x8001, len(body), 0, False, phone, serial)
    return Message(h, body)


def build_8100(reply_serial: int, result: int, auth_code: str, phone: str,
               serial: int) -> Message:
    body = struct.pack(">HB", reply_serial, result)
    if result == 0:
        body += auth_code.encode("gbk")
    h = Header(0x8100, len(body), 0, False, phone, serial)
    return Message(h, body)


def build_8103(params: list[tuple[int, bytes]], phone: str,
               serial: int) -> Message:
    body = bytes([len(params)])
    for pid, val in params:
        body += struct.pack(">IB", pid, len(val)) + val
    h = Header(0x8103, len(body), 0, False, phone, serial)
    return Message(h, body)


def build_8104(phone: str, serial: int) -> Message:
    return Message(Header(0x8104, 0, 0, False, phone, serial), b"")


def build_8105(cmd: int, cmd_param: str, phone: str, serial: int) -> Message:
    body = bytes([cmd]) + cmd_param.encode("gbk")
    return Message(Header(0x8105, len(body), 0, False, phone, serial), body)


def build_8201(phone: str, serial: int) -> Message:
    return Message(Header(0x8201, 0, 0, False, phone, serial), b"")


def build_8300(flag: int, text: str, phone: str, serial: int) -> Message:
    body = bytes([flag]) + text.encode("gbk")[:1024]
    return Message(Header(0x8300, len(body), 0, False, phone, serial), body)


# common param encoders (table 11)
def p_dword(v: int) -> bytes: return struct.pack(">I", v)
def p_str(v: str) -> bytes: return v.encode("gbk")
