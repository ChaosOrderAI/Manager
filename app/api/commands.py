"""Downlink commands: set params, query params, reset, query location, text.

Terminals like the RM68S are mostly offline (dial-up tracker pattern):
short TCP bursts every ~60s. Commands submitted while offline are queued
in command_log (status='pending', serial=0); the gateway flushes them as
soon as the terminal next registers/authenticates.
"""
import json
import struct
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.api.deps import require_token
from app.models.db import get_db
from app.models.entities import CommandLog, Device
from app.schemas.dto import ParamSet, TextDownlink
from app.services import repository as repo
from gateway.protocol import messages as M
from gateway.server.tcp_server import server

router = APIRouter(prefix="/api/commands", tags=["commands"],
                   dependencies=[Depends(require_token)])

DWORD_PARAMS = {0x0001, 0x0018, 0x0027, 0x0029, 0x0055, 0x0056, 0x0080}
STR_PARAMS = {0x0010, 0x0013}
_UTC8 = timedelta(hours=8)


async def _dev_or_404(terminal_id: str, db: AsyncSession) -> Device:
    dev = (await db.execute(select(Device).where(
        Device.terminal_id == terminal_id))).scalar_one_or_none()
    if not dev:
        raise HTTPException(404, "unknown terminal")
    return dev


async def _queue_or_send(db: AsyncSession, terminal_id: str, msg_id: int,
                         builder, payload_desc: str):
    """Online -> build+send now.  Offline -> enqueue in command_log
    (status=pending, serial=0); session._flush_pending will send on
    next register/auth."""
    dev = await _dev_or_404(terminal_id, db)
    sess = server.session_for(dev.phone)
    if sess is None:
        # 入队:status=pending, serial=0,payload 存 JSON {msg_id, args}
        await repo.log_command(db, terminal_id, msg_id, 0, payload_desc,
                               status="pending")
        await db.commit()
        return {"ok": True, "queued": True}
    serial = sess.serial.next()
    await sess.send(builder(dev.phone, serial))
    await repo.log_command(db, terminal_id, msg_id, serial, payload_desc,
                           status="sent")
    await db.commit()
    return {"ok": True, "queued": False, "serial": serial}


@router.post("/{terminal_id}/params")
async def set_params(terminal_id: str, body: ParamSet,
                     db: AsyncSession = Depends(get_db)):
    # params 转成 (pid, hex_str) 列表入队,flush 时再还原成 bytes
    items: list[tuple[int, bytes]] = []
    for k, v in body.params.items():
        try:
            pid = int(k, 0)
        except (TypeError, ValueError):
            raise HTTPException(400, f"invalid param id: {k!r}")
        if not (0 <= pid <= 0xFFFFFFFF):
            raise HTTPException(400, f"param id out of range: {k!r}")
        try:
            val = M.p_dword(int(v)) if pid in DWORD_PARAMS else M.p_str(str(v))
        except (TypeError, ValueError):
            raise HTTPException(400, f"invalid value for param {k!r}: {v!r}")
        items.append((pid, val))
    desc = json.dumps({"params": {pid: v.hex() for pid, v in items}})
    return await _queue_or_send(
        db, terminal_id, 0x8103,
        lambda phone, serial: M.build_8103(items, phone, serial), desc)


@router.post("/{terminal_id}/params/query")
async def query_params(terminal_id: str, db: AsyncSession = Depends(get_db)):
    return await _queue_or_send(
        db, terminal_id, 0x8104,
        lambda phone, serial: M.build_8104(phone, serial), "")


@router.post("/{terminal_id}/reset")
async def reset(terminal_id: str, db: AsyncSession = Depends(get_db)):
    return await _queue_or_send(
        db, terminal_id, 0x8105,
        lambda phone, serial: M.build_8105(4, "", phone, serial), "reset")


@router.post("/{terminal_id}/locate")
async def locate(terminal_id: str, db: AsyncSession = Depends(get_db)):
    return await _queue_or_send(
        db, terminal_id, 0x8201,
        lambda phone, serial: M.build_8201(phone, serial), "query location")


@router.post("/{terminal_id}/text")
async def text(terminal_id: str, body: TextDownlink,
               db: AsyncSession = Depends(get_db)):
    desc = json.dumps({"flag": body.flag, "text": body.text[:200]})
    return await _queue_or_send(
        db, terminal_id, 0x8300,
        lambda phone, serial: M.build_8300(body.flag, body.text,
                                           phone, serial),
        desc)


@router.get("/{terminal_id}/pending")
async def list_pending(terminal_id: str, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(CommandLog).where(CommandLog.terminal_id == terminal_id,
                                 CommandLog.status == "pending")
        .order_by(CommandLog.sent_at))).scalars().all()
    return [{"id": r.id, "msg_id": r.msg_id, "payload": r.payload,
             "queued_at": r.sent_at.isoformat()} for r in rows]


async def flush_pending(db: AsyncSession, terminal_id: str, sess) -> int:
    """Send all queued commands for terminal. Returns count sent."""
    rows = (await db.execute(
        select(CommandLog).where(CommandLog.terminal_id == terminal_id,
                                 CommandLog.status == "pending")
        .order_by(CommandLog.sent_at))).scalars().all()
    sent = 0
    for c in rows:
        try:
            payload = json.loads(c.payload) if c.payload else {}
        except json.JSONDecodeError:
            payload = {}
        serial = sess.serial.next()
        msg = _rebuild(c.msg_id, payload, sess.phone, serial)
        if msg is None:
            await db.execute(
                update(CommandLog).where(CommandLog.id == c.id)
                .values(status="failed"))
            continue
        try:
            await sess.send(msg)
        except Exception:
            break                       # socket died; keep pending
        await db.execute(
            update(CommandLog).where(CommandLog.id == c.id)
            .values(status="sent", serial=serial,
                    sent_at=datetime.utcnow() + _UTC8))
        sent += 1
    return sent


def _rebuild(msg_id: int, payload: dict, phone: str, serial: int):
    """Rebuild a downlink Message from its queue payload."""
    if msg_id == 0x8103:
        items = [(int(k), bytes.fromhex(v))
                 for k, v in payload.get("params", {}).items()]
        return M.build_8103(items, phone, serial)
    if msg_id == 0x8104:
        return M.build_8104(phone, serial)
    if msg_id == 0x8105:
        return M.build_8105(4, "", phone, serial)
    if msg_id == 0x8201:
        return M.build_8201(phone, serial)
    if msg_id == 0x8300:
        return M.build_8300(payload.get("flag", 0),
                            payload.get("text", ""), phone, serial)
    return None
