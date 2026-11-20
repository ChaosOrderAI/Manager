from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_token
from app.models.db import get_db
from app.models.entities import Alarm
from app.schemas.dto import AlarmOut

router = APIRouter(prefix="/api/alarms", tags=["alarms"],
                   dependencies=[Depends(require_token)])


@router.get("", response_model=list[AlarmOut])
async def list_alarms(active: bool | None = None,
                      terminal_id: str | None = None,
                      db: AsyncSession = Depends(get_db)):
    q = select(Alarm).order_by(Alarm.triggered_at.desc()).limit(1000)
    if active is not None:
        q = q.where(Alarm.active.is_(active))
    if terminal_id:
        q = q.where(Alarm.terminal_id == terminal_id)
    return list((await db.execute(q)).scalars())


@router.post("/{alarm_id}/ack")
async def ack(alarm_id: int, by: str = "",
              db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        update(Alarm).where(Alarm.id == alarm_id)
        .values(acknowledged_at=datetime.utcnow() + timedelta(hours=8),
                ack_by=by))
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(404)
    return {"ok": True}


@router.post("/{alarm_id}/close")
async def close(alarm_id: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        update(Alarm).where(Alarm.id == alarm_id)
        .values(active=False,
                closed_at=datetime.utcnow() + timedelta(hours=8)))
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(404)
    return {"ok": True}
