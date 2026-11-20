"""压力测试: N 个并发终端, 注册+鉴权+连续位置上报, 统计吞吐/错误/延迟.

Usage:
    python tools/stress.py --num 50 --duration 60 --rate 1.0
    python tools/stress.py --num 200 --duration 30 --rate 0.2
"""
import argparse
import asyncio
import math
import struct
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway.protocol.codec import FrameDecoder, Header, Message, encode


def reg_body(tid: str):
    return (struct.pack(">HH", 11, 1101) + b"12345"
            + b"M68S" + b"\x00" * 16
            + tid.encode().ljust(7, b"\x00")[:7]
            + bytes([1]) + b"STRESS")


def loc_body(lat: float, lng: float):
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)
    bcd = bytes([((now.year - 2000) // 10) << 4 | (now.year - 2000) % 10,
                 (now.month // 10) << 4 | now.month % 10,
                 (now.day // 10) << 4 | now.day % 10,
                 (now.hour // 10) << 4 | now.hour % 10,
                 (now.minute // 10) << 4 | now.minute % 10,
                 (now.second // 10) << 4 | now.second % 10])
    return (struct.pack(">II", 0, 0x3)
            + struct.pack(">II", int(lat * 1e6), int(lng * 1e6))
            + struct.pack(">HHH", 50, 300, 90) + bcd)


def frame(mid, body, phone, serial):
    return encode(Message(Header(mid, len(body), 0, False, phone, serial), body))


STATS = Counter()


async def terminal(idx: int, args):
    tid = f"T{idx:05d}"[-7:]
    phone = f"0138{idx:08d}"[-12:]
    lat0 = args.lat + (idx % 20) * 0.005
    lng0 = args.lng + (idx // 20) * 0.005

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(args.host, args.port), timeout=10)
    except Exception:
        STATS["connect_fail"] += 1
        return

    dec = FrameDecoder()
    serial = 0

    async def send(mid, body):
        nonlocal serial
        serial += 1
        writer.write(frame(mid, body, phone, serial))
        await writer.drain()

    async def pump_until(want_id, timeout=5):
        t0 = time.monotonic()
        buf = b""
        while time.monotonic() - t0 < timeout:
            try:
                data = await asyncio.wait_for(reader.read(4096),
                                              timeout=timeout - (time.monotonic() - t0))
            except asyncio.TimeoutError:
                break
            if not data:
                break
            buf += data
            for m in dec.feed(data):
                if m.header.msg_id == want_id:
                    return m
        STATS[f"timeout_{want_id:04x}"] += 1
        return None

    # register
    await send(0x0100, reg_body(tid))
    m = await pump_until(0x8100)
    if not m or m.body[2] != 0:
        STATS["register_fail"] += 1
        writer.close(); return
    auth = m.body[3:] if len(m.body) > 3 else b""
    # auth
    await send(0x0102, auth)
    m = await pump_until(0x8001)
    if not m or m.body[4] != 0:
        STATS["auth_fail"] += 1
        writer.close(); return
    STATS["authed"] += 1

    # location loop
    t_end = time.monotonic() + args.duration
    i = 0
    while time.monotonic() < t_end:
        lat = lat0 + 0.001 * math.sin(i * 0.2)
        lng = lng0 + 0.001 * math.cos(i * 0.2)
        t0 = time.monotonic()
        try:
            await send(0x0200, loc_body(lat, lng))
            m = await pump_until(0x8001, timeout=3)
            if m:
                STATS["loc_ok"] += 1
                STATS[f"loc_latency_{min(int((time.monotonic()-t0)*1000)//10*10, 990)}ms"] += 1
            else:
                STATS["loc_timeout"] += 1
        except Exception:
            STATS["loc_send_fail"] += 1
            break
        i += 1
        await asyncio.sleep(args.rate)
    writer.close()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7808)
    ap.add_argument("--num", type=int, default=50)
    ap.add_argument("--duration", type=float, default=60)
    ap.add_argument("--rate", type=float, default=1.0, help="sec between loc reports per terminal")
    ap.add_argument("--lat", type=float, default=39.90)
    ap.add_argument("--lng", type=float, default=116.38)
    ap.add_argument("--stagger", type=float, default=0.05, help="sec between terminal starts")
    args = ap.parse_args()

    print(f"stress: {args.num} terminals, {args.duration}s, {args.rate}s interval")
    t0 = time.monotonic()
    tasks = []
    for i in range(args.num):
        tasks.append(asyncio.create_task(terminal(i, args)))
        await asyncio.sleep(args.stagger)
    await asyncio.gather(*tasks, return_exceptions=True)
    elapsed = time.monotonic() - t0

    loc_ok = STATS["loc_ok"]
    print(f"\n=== results ({elapsed:.1f}s) ===")
    for k in sorted(STATS):
        if k.startswith("loc_latency_"):
            continue
        print(f"  {k}: {STATS[k]}")
    if loc_ok:
        lats = [(int(k.split('_')[2].rstrip('ms')), v)
                for k, v in STATS.items() if k.startswith("loc_latency_")]
        lats.sort()
        cum, p50 = p95 = 0, None
        for ms, c in lats:
            cum += c
            if p50 is None and cum >= loc_ok * 0.5: p50 = ms
            if p95 is None and cum >= loc_ok * 0.95: p95 = ms
        print(f"  loc throughput: {loc_ok/elapsed:.1f} msg/s")
        print(f"  loc latency p50={p50}ms p95={p95}ms")


if __name__ == "__main__":
    asyncio.run(main())
