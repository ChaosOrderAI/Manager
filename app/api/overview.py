from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_token
from app.models.db import get_db
from app.models.entities import Alarm, Device, DeviceState
from app.schemas.dto import OverviewOut

router = APIRouter(prefix="/api/overview", tags=["overview"],
                   dependencies=[Depends(require_token)])


@router.get("", response_model=OverviewOut)
async def overview(db: AsyncSession = Depends(get_db)):
    total = (await db.execute(select(func.count(Device.id)).where(
        Device.unbound.is_(False)))).scalar() or 0
    online = (await db.execute(select(func.count(DeviceState.terminal_id))
              .where(DeviceState.online.is_(True)))).scalar() or 0
    on_batt = (await db.execute(select(func.count(DeviceState.terminal_id))
               .where(DeviceState.external_power.is_(False)))).scalar() or 0
    alarms = (await db.execute(select(func.count(Alarm.id)).where(
        Alarm.active.is_(True)))).scalar() or 0
    return OverviewOut(total=total, online=online, on_battery=on_batt,
                       active_alarms=alarms)


@router.get("/map")
async def map_devices(db: AsyncSession = Depends(get_db)):
    """All device states for the live map (定位总览)."""
    rows = (await db.execute(
        select(DeviceState, Device)
        .join(Device, Device.terminal_id == DeviceState.terminal_id,
              isouter=True))).all()
    out = []
    for st, dev in rows:
        out.append({
            "terminal_id": st.terminal_id,
            "asset_no": dev.asset_no if dev else None,
            "brand": dev.brand if dev else None,
            "model": dev.model if dev else None,
            "online": st.online, "lat": st.lat, "lng": st.lng,
            "located": st.located, "loc_source": st.loc_source,
            "battery_pct": st.battery_pct,
            "external_power": st.external_power,
            "located_at": st.located_at, "last_comm_at": st.last_comm_at,
            "iccid": st.iccid, "imei": st.imei, "product_id": st.product_id,
            "acc_on": st.acc_on, "work_mode": st.work_mode,
            "report_interval": st.report_interval,
            "ext_voltage_mv": st.ext_voltage_mv, "charging": st.charging,
        })
    return out
