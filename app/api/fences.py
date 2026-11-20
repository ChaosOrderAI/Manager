import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_token
from app.models.db import get_db
from app.models.entities import Fence, FenceEvent
from app.schemas.dto import FenceIn, FenceOut

router = APIRouter(prefix="/api/fences", tags=["fences"],
                   dependencies=[Depends(require_token)])


def _to_orm(body: FenceIn) -> dict:
    d = body.model_dump()
    d["devices"] = json.dumps(d["devices"])   # store as JSON text
    return d


def _out(f: Fence) -> FenceOut:
    return FenceOut.from_orm_fence(f)


@router.post("", response_model=FenceOut)
async def create(body: FenceIn, db: AsyncSession = Depends(get_db)):
    f = Fence(**_to_orm(body))
    db.add(f)
    await db.commit()
    await db.refresh(f)
    return _out(f)


@router.get("", response_model=list[FenceOut])
async def list_fences(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Fence))).scalars().all()
    return [_out(f) for f in rows]


@router.get("/events")
async def events(terminal_id: str | None = None,
                 db: AsyncSession = Depends(get_db)):
    q = select(FenceEvent).order_by(FenceEvent.happened_at.desc()).limit(500)
    if terminal_id:
        q = q.where(FenceEvent.terminal_id == terminal_id)
    rows = (await db.execute(q)).scalars()
    return [{"id": e.id, "fence_id": e.fence_id, "terminal_id": e.terminal_id,
             "event": e.event, "lat": e.lat, "lng": e.lng,
             "happened_at": e.happened_at} for e in rows]


@router.get("/{fence_id}", response_model=FenceOut)
async def get_fence(fence_id: int, db: AsyncSession = Depends(get_db)):
    f = await db.get(Fence, fence_id)
    if not f:
        raise HTTPException(404)
    return _out(f)


@router.put("/{fence_id}", response_model=FenceOut)
async def update(fence_id: int, body: FenceIn,
                 db: AsyncSession = Depends(get_db)):
    f = await db.get(Fence, fence_id)
    if not f:
        raise HTTPException(404)
    for k, v in _to_orm(body).items():
        setattr(f, k, v)
    await db.commit()
    await db.refresh(f)
    return _out(f)


@router.post("/{fence_id}/toggle")
async def toggle(fence_id: int, db: AsyncSession = Depends(get_db)):
    f = await db.get(Fence, fence_id)
    if not f:
        raise HTTPException(404)
    f.enabled = not f.enabled
    await db.commit()
    return {"enabled": f.enabled}


@router.delete("/{fence_id}")
async def delete(fence_id: int, db: AsyncSession = Depends(get_db)):
    f = await db.get(Fence, fence_id)
    if not f:
        raise HTTPException(404)
    await db.delete(f)
    await db.commit()
    return {"ok": True}
