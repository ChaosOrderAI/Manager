from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_token
from app.models.db import get_db
from app.models.entities import Device, DeviceState
from app.schemas.dto import DeviceIn, DeviceOut, DeviceStateOut

router = APIRouter(prefix="/api/devices", tags=["devices"],
                   dependencies=[Depends(require_token)])


@router.post("", response_model=DeviceOut)
async def create_device(body: DeviceIn, db: AsyncSession = Depends(get_db)):
    if (await db.execute(select(Device).where(
            Device.phone == body.phone))).scalar_one_or_none():
        raise HTTPException(409, "phone already bound")
    dev = Device(**body.model_dump())
    db.add(dev)
    await db.commit()
    await db.refresh(dev)
    return dev


@router.get("", response_model=list[DeviceOut])
async def list_devices(db: AsyncSession = Depends(get_db)):
    return list((await db.execute(
        select(Device).where(Device.unbound.is_(False)))).scalars())


@router.get("/{terminal_id}", response_model=DeviceOut)
async def get_device(terminal_id: str, db: AsyncSession = Depends(get_db)):
    dev = (await db.execute(select(Device).where(
        Device.terminal_id == terminal_id))).scalar_one_or_none()
    if not dev:
        raise HTTPException(404)
    return dev


@router.get("/{terminal_id}/state", response_model=DeviceStateOut)
async def get_state(terminal_id: str, db: AsyncSession = Depends(get_db)):
    st = (await db.execute(select(DeviceState).where(
        DeviceState.terminal_id == terminal_id))).scalar_one_or_none()
    if not st:
        raise HTTPException(404)
    return st


@router.post("/{terminal_id}/unbind")
async def unbind(terminal_id: str, db: AsyncSession = Depends(get_db)):
    dev = (await db.execute(select(Device).where(
        Device.terminal_id == terminal_id))).scalar_one_or_none()
    if not dev:
        raise HTTPException(404)
    dev.unbound = True
    await db.commit()
    return {"ok": True}
