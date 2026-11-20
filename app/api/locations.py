from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_token
from app.models.db import get_db
from app.models.entities import LocationRecord
from app.schemas.dto import LocationOut

router = APIRouter(prefix="/api/locations", tags=["locations"],
                   dependencies=[Depends(require_token)])


@router.get("/{terminal_id}/history", response_model=list[LocationOut])
async def history(terminal_id: str,
                  start: datetime | None = Query(None),
                  end: datetime | None = Query(None),
                  last: int | None = Query(None, le=10000),
                  limit: int = Query(5000, le=50000),
                  db: AsyncSession = Depends(get_db)):
    q = select(LocationRecord).where(
        LocationRecord.terminal_id == terminal_id)
    if start:
        q = q.where(LocationRecord.collected_at >= start)
    if end:
        q = q.where(LocationRecord.collected_at <= end)
    q = q.order_by(LocationRecord.collected_at.desc())
    if last:
        q = q.limit(last)
    else:
        q = q.limit(limit)
    rows = list((await db.execute(q)).scalars())
    rows.reverse()                       # chronological order for polyline
    return rows


@router.get("/{terminal_id}/latest", response_model=LocationOut)
async def latest(terminal_id: str, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        select(LocationRecord)
        .where(LocationRecord.terminal_id == terminal_id)
        .order_by(LocationRecord.collected_at.desc())
        .limit(1))).scalar_one_or_none()
    if not row:
        raise HTTPException(404)
    return row
