"""DB access helpers shared by gateway and API."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

_UTC8 = timedelta(hours=8)

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import engine

from app.models.entities import (Alarm, CommandLog, Device, DeviceState,
                                 FenceEvent, LocationRecord)


async def device_by_phone(db: AsyncSession, phone: str) -> Optional[Device]:
    return (await db.execute(
        select(Device).where(Device.phone == phone))).scalar_one_or_none()


async def device_by_terminal(db: AsyncSession, tid: str) -> Optional[Device]:
    return (await db.execute(
        select(Device).where(Device.terminal_id == tid))).scalar_one_or_none()


async def get_state(db: AsyncSession, tid: str) -> DeviceState:
    st = (await db.execute(
        select(DeviceState).where(DeviceState.terminal_id == tid))
    ).scalar_one_or_none()
    if st is None:
        st = DeviceState(terminal_id=tid)
        db.add(st)
    return st


async def save_location(db: AsyncSession, st: DeviceState, *, loc, source: str,
                        battery_pct: Optional[int], external: bool):
    if engine.dialect.name == "postgresql":
        from geoalchemy2.functions import ST_MakePoint, ST_SetSRID
        geom = ST_SetSRID(ST_MakePoint(loc.lng, loc.lat), 4326)
    else:
        geom = f"{loc.lng},{loc.lat}"
    rec = LocationRecord(
        terminal_id=st.terminal_id,
        msg_serial=getattr(loc, "_serial", 0),
        lat=loc.lat, lng=loc.lng, altitude=loc.altitude,
        speed=loc.speed, direction=loc.direction,
        located=loc.positioned,
        # BCD 时间缺失/非法时标记为 last,避免把接收时间误当采集时间
        loc_source=source if loc.time else f"{source}_notime",
        alarm_bits=loc.alarm, status_bits=loc.status,
        battery_pct=battery_pct, external_power=external,
        # 设备 BCD 是 UTC+8,fallback 也用 UTC+8 保持口径一致
        collected_at=loc.time or (datetime.utcnow() + _UTC8),
        geom=geom,
    )
    db.add(rec)

    st.lat, st.lng = loc.lat, loc.lng
    st.altitude, st.speed, st.direction = loc.altitude, loc.speed, loc.direction
    st.located, st.located_at = loc.positioned, loc.time
    st.loc_source = source
    st.alarm_bits, st.status_bits = loc.alarm, loc.status
    st.acc_on = loc.acc_on
    if battery_pct is not None:
        st.battery_pct = battery_pct
    st.external_power = external


async def raise_alarm(db: AsyncSession, terminal_id: str, type_: str,
                      detail: str = "", level: str = "warn") -> Alarm:
    """Raise if no active alarm of same type; return the alarm."""
    existing = (await db.execute(
        select(Alarm).where(Alarm.terminal_id == terminal_id,
                            Alarm.type == type_, Alarm.active.is_(True)))
    ).scalar_one_or_none()
    if existing:
        if detail and existing.detail != detail:
            existing.detail = detail          # update detail in place
        return existing
    a = Alarm(terminal_id=terminal_id, type=type_, detail=detail, level=level)
    db.add(a)
    return a


async def resolve_alarm(db: AsyncSession, terminal_id: str, type_: str):
    await db.execute(
        update(Alarm)
        .where(Alarm.terminal_id == terminal_id, Alarm.type == type_,
               Alarm.active.is_(True))
        .values(active=False, recovered_at=datetime.utcnow() + _UTC8))


async def log_command(db: AsyncSession, terminal_id: str, msg_id: int,
                      serial: int, payload: str,
                      status: str = "sent") -> CommandLog:
    c = CommandLog(terminal_id=terminal_id, msg_id=msg_id, serial=serial,
                   payload=payload, status=status,
                   sent_at=datetime.utcnow() + _UTC8)
    db.add(c)
    return c


async def ack_command(db: AsyncSession, terminal_id: str, reply_serial: int,
                      reply_id: int, result: int):
    await db.execute(
        update(CommandLog)
        .where(CommandLog.terminal_id == terminal_id,
               CommandLog.msg_id == reply_id,
               CommandLog.serial == reply_serial)
        .values(ack_result=result, acked_at=datetime.utcnow() + _UTC8))
