"""JT/T 808 message codec: escaping, checksum, header/body pack & parse.

Protocol reference: M68S+FM934客户专用部标协议.doc (based on JT/T 794 / 808).
Wire format:
    0x7e | header | body | checksum | 0x7e
checksum = XOR of all bytes from header start through last body byte.
Escaping: 0x7e -> 0x7d 0x02 ; 0x7d -> 0x7d 0x01  (applied to header+body+checksum)
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Optional

FLAG = 0x7E
ESCAPE = 0x7D


class CodecError(Exception):
    pass


def escape(data: bytes) -> bytes:
    """Escape 0x7e / 0x7d inside the payload (header+body+checksum)."""
    out = bytearray()
    for b in data:
        if b == 0x7E:
            out += b"\x7d\x02"
        elif b == 0x7D:
            out += b"\x7d\x01"
        else:
            out.append(b)
    return bytes(out)


def unescape(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b == 0x7D:
            if i + 1 >= len(data):
                raise CodecError("truncated escape sequence")
            nxt = data[i + 1]
            if nxt == 0x02:
                out.append(0x7E)
            elif nxt == 0x01:
                out.append(0x7D)
            else:
                raise CodecError(f"invalid escape byte 0x{nxt:02x}")
            i += 2
        else:
            out.append(b)
            i += 1
    return bytes(out)


def checksum(data: bytes) -> int:
    c = 0
    for b in data:
        c ^= b
    return c


@dataclass
class Header:
    msg_id: int
    body_len: int          # low 10 bits of body attr
    encrypt: int           # bits 10-12
    subcontract: bool      # bit 13
    phone: str             # BCD[6] -> 12-digit string
    serial: int            # WORD
    pkg_total: Optional[int] = None   # present when subcontract
    pkg_seq: Optional[int] = None

    @property
    def body_attr(self) -> int:
        attr = self.body_len & 0x03FF
        attr |= (self.encrypt & 0x07) << 10
        if self.subcontract:
            attr |= 1 << 13
        return attr


@dataclass
class Message:
    header: Header
    body: bytes = b""


def _bcd_to_str(b: bytes) -> str:
    return "".join(f"{x >> 4}{x & 0x0F}" for x in b)


def _str_to_bcd(s: str, nbytes: int = 6) -> bytes:
    s = s.rjust(nbytes * 2, "0")[-nbytes * 2:]
    return bytes(int(s[i], 16) * 16 + int(s[i + 1], 16) for i in range(0, len(s), 2))


def pack_header(h: Header) -> bytes:
    out = struct.pack(">HH", h.msg_id, h.body_attr)
    out += _str_to_bcd(h.phone)
    out += struct.pack(">H", h.serial)
    if h.subcontract:
        out += struct.pack(">HH", h.pkg_total or 1, h.pkg_seq or 1)
    return out


def parse_header(data: bytes) -> tuple[Header, int]:
    """Parse header; returns (header, consumed_len)."""
    if len(data) < 12:
        raise CodecError("header too short")
    msg_id, attr = struct.unpack(">HH", data[0:4])
    body_len = attr & 0x03FF
    encrypt = (attr >> 10) & 0x07
    subcontract = bool(attr & (1 << 13))
    phone = _bcd_to_str(data[4:10])
    serial = struct.unpack(">H", data[10:12])[0]
    consumed = 12
    pkg_total = pkg_seq = None
    if subcontract:
        pkg_total, pkg_seq = struct.unpack(">HH", data[12:16])
        consumed = 16
    return Header(msg_id, body_len, encrypt, subcontract, phone, serial,
                  pkg_total, pkg_seq), consumed


def encode(msg: Message) -> bytes:
    """Full wire frame: 0x7e + escaped(header+body+checksum) + 0x7e."""
    raw = pack_header(msg.header) + msg.body
    frame = bytes([FLAG]) + escape(raw + bytes([checksum(raw)])) + bytes([FLAG])
    return frame


def decode_frame(frame: bytes) -> Message:
    """Decode one complete frame (including 0x7e flags)."""
    if len(frame) < 2 or frame[0] != FLAG or frame[-1] != FLAG:
        raise CodecError("bad frame flags")
    raw = unescape(frame[1:-1])
    if len(raw) < 13:
        raise CodecError("frame too short")
    payload, chk = raw[:-1], raw[-1]
    if checksum(payload) != chk:
        raise CodecError(f"checksum mismatch: got 0x{chk:02x}")
    header, hlen = parse_header(payload)
    body = payload[hlen:hlen + header.body_len]
    if len(body) != header.body_len:
        raise CodecError("body length mismatch")
    return Message(header=header, body=body)


class FrameDecoder:
    """Incremental stream decoder — feed TCP bytes, get complete Messages."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[Message]:
        self._buf += data
        msgs: list[Message] = []
        while True:
            start = self._buf.find(FLAG)
            if start < 0:
                self._buf.clear()
                break
            if start > 0:
                del self._buf[:start]
            end = self._buf.find(FLAG, 1)
            if end < 0:
                break  # wait for more data
            frame = bytes(self._buf[:end + 1])
            del self._buf[:end + 1]
            if len(frame) <= 2:
                continue  # empty frame (consecutive flags)
            try:
                msgs.append(decode_frame(frame))
            except CodecError:
                continue  # drop bad frame, keep scanning
        return msgs
