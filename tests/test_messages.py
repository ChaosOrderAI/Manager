import struct
from datetime import datetime

from gateway.protocol import messages as M
from gateway.protocol.codec import Header


def _loc_body():
    alarm = 0x00000002          # bit1 overspeed
    status = 0x00000003         # ACC on + positioned
    lat = int(39.908722 * 1e6)
    lng = int(116.397470 * 1e6)
    return (struct.pack(">II", alarm, status)
            + struct.pack(">II", lat, lng)
            + struct.pack(">HHH", 55, 612, 90)
            + bytes([0x26, 0x11, 0x18, 0x12, 0x30, 0x45]))  # BCD time


def test_parse_0200():
    loc = M.parse_0200(_loc_body())
    assert loc.positioned and loc.acc_on
    assert abs(loc.lat - 39.908722) < 1e-5
    assert abs(loc.lng - 116.397470) < 1e-5
    assert loc.speed == 61.2
    assert loc.altitude == 55
    assert loc.time == datetime(2026, 11, 18, 12, 30, 45)


def test_parse_0100_register():
    body = (struct.pack(">HH", 11, 1101)
            + b"12345"                     # manufacturer
            + b"M68S" + b"\x00" * 16       # 20-byte model field
            + b"TERM001"                   # 7-byte terminal id
            + bytes([1])                   # plate color
            + "京A12345".encode("gbk"))
    reg = M.parse_0100(body)
    assert reg.province == 11 and reg.city == 1101
    assert reg.model == "M68S"
    assert reg.terminal_id == "TERM001"
    assert reg.plate_color == 1
    assert reg.plate == "京A12345"


def test_build_8001_roundtrip_header():
    msg = M.build_8001(9, 0x0200, 0, "013812345678", 3)
    assert msg.header.msg_id == 0x8001
    assert msg.body == struct.pack(">HHB", 9, 0x0200, 0)


def test_build_8103_params():
    msg = M.build_8103([(0x0001, M.p_dword(30)),
                        (0x0013, M.p_str("srv.example.com"))],
                       "013812345678", 1)
    assert msg.body[0] == 2
    assert msg.header.body_len == len(msg.body)
