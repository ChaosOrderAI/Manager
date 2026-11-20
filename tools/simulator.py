"""M68 terminal simulator — exercises register -> auth -> heartbeat ->
location -> alarms against the gateway. Usage:

    python tools/simulator.py --host 127.0.0.1 --port 7808 \
        --phone 013812345678 --count 5
"""
import argparse
import asyncio
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway.protocol.codec import FrameDecoder, Header, Message, encode
from gateway.protocol import messages as M


def _ext(cmd: int, data: bytes) -> bytes:
    """附录D扩展指令: WORD len(cmd+data) | WORD cmd | data."""
    return struct.pack(">HH", len(data) + 2, cmd) + data


def frame(msg_id: int, body: bytes, phone: str, serial: int) -> bytes:
    return encode(Message(Header(msg_id, len(body), 0, False, phone, serial),
                          body))


def reg_body(tid: str = "SIMTERM"):
    return (struct.pack(">HH", 11, 1101)
            + b"12345"
            + b"M68S" + b"\x00" * 16
            + tid.encode().ljust(7, b"\x00")[:7]
            + bytes([1])
            + f"京A{tid[-5:]}".encode("gbk"))


def loc_body(lat: float, lng: float, alarm: int = 0,
             batt: int = 90) -> bytes:
    import datetime as dt
    now = dt.datetime.utcnow() + dt.timedelta(hours=8)
    bcd = bytes([((now.year - 2000) // 10) << 4 | (now.year - 2000) % 10,
                 (now.month // 10) << 4 | now.month % 10,
                 (now.day // 10) << 4 | now.day % 10,
                 (now.hour // 10) << 4 | now.hour % 10,
                 (now.minute // 10) << 4 | now.minute % 10,
                 (now.second // 10) << 4 | now.second % 10])
    ext = _ext(0x00A8, bytes([batt])) + _ext(0x002D, struct.pack(">H", 12000))
    extras = bytes([0x30, len(ext)]) + ext
    return (struct.pack(">II", alarm, 0x00000003)
            + struct.pack(">II", int(lat * 1e6), int(lng * 1e6))
            + struct.pack(">HHH", 50, 300, 90)
            + bcd + extras)


import math
import random

def _path(idx: int, i: int, lat0: float, lng0: float):
    """Return (lat,lng) for terminal idx at step i. Patterns:
    0 circle, 1 line NE, 2 square, 3 zigzag, 4 random walk, 5 small circle.
    """
    mode = idx % 6
    if mode == 0:                                     # 圆 半径~300m
        a = i * 0.35
        return lat0 + 0.003 * math.cos(a), lng0 + 0.003 * math.sin(a)
    if mode == 1:                                     # 东北直线 往返
        t = (i % 40) * 0.0004
        return lat0 + t, lng0 + t
    if mode == 2:                                     # 正方形 边长~350m
        seg = (i // 10) % 4
        off = (i % 10) * 0.00035
        if seg == 0:   return lat0 + off, lng0
        if seg == 1:   return lat0 + 0.0035, lng0 + off
        if seg == 2:   return lat0 + 0.0035 - off, lng0 + 0.0035
        return lat0, lng0 + 0.0035 - off
    if mode == 3:                                     # 之字
        return lat0 + (i * 0.0005), lng0 + ((i // 5) % 2) * 0.004 + (i % 5) * 0.0008
    if mode == 4:                                     # 随机游走
        random.seed(idx * 1000 + i // 3)
        return (lat0 + math.sin(i * 0.2) * 0.003 + random.uniform(-0.0005, 0.0005),
                lng0 + math.cos(i * 0.2) * 0.003 + random.uniform(-0.0005, 0.0005))
    # mode 5: 小圆 半径~150m 反向
    a = i * 0.5
    return lat0 + 0.0015 * math.cos(a), lng0 - 0.0015 * math.sin(a)


async def run_terminal(args, idx: int):
    """One simulated terminal: its own phone/terminal_id/track."""
    phone = f"0138{idx:08d}"[-12:]
    tid = f"TERM{idx:03d}"
    lat0 = args.lat + idx * 0.004
    lng0 = args.lng + idx * 0.004

    reader, writer = await asyncio.open_connection(args.host, args.port)
    dec = FrameDecoder()
    serial = 0

    async def send(mid, body):
        nonlocal serial
        serial += 1
        writer.write(frame(mid, body, phone, serial))
        await writer.drain()

    async def pump():
        data = await reader.read(4096)
        for m in dec.feed(data or b""):
            print(f"[{tid}] << 0x{m.header.msg_id:04x}")

    await send(0x0100, reg_body(tid))
    await pump()
    await send(0x0102, f"{tid}-{tid}".encode())
    await pump()

    for i in range(args.count):
        lat, lng = _path(idx, i, lat0, lng0)
        # overspeed alarm only during steps 20-30 so one raise/resolve pair
        alarm = 0x00000002 if 20 <= i < 30 else 0
        batt = max(5, 95 - i // 3)
        await send(0x0200, loc_body(lat, lng, alarm=alarm, batt=batt))
        await pump()
        await asyncio.sleep(args.interval)
    writer.close()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7808)
    ap.add_argument("--count", type=int, default=30)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--num", type=int, default=1, help="number of terminals")
    ap.add_argument("--lat", type=float, default=39.9087)
    ap.add_argument("--lng", type=float, default=116.3974)
    args = ap.parse_args()

    await asyncio.gather(*(run_terminal(args, i) for i in range(args.num)))


if __name__ == "__main__":
    asyncio.run(main())
