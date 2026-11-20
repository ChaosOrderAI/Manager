"""Periodic watchdog: mark terminals offline & raise offline/loc_expired
alarms when no message arrives within OFFLINE_TIMEOUT_SEC."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.models.db import SessionLocal
from app.models.entities import DeviceState
from app.services import repository as repo

log = logging.getLogger("watchdog")


async def watchdog_loop():
    while True:
        await asyncio.sleep(30)
        try:
            await _sweep()
        except Exception:
            log.exception("watchdog sweep failed")


async def _sweep():
    # DB 口径为 UTC+8 naive,cutoff 与 last_comm_at 一致
    cutoff = (datetime.utcnow() + timedelta(hours=8)
              ) - timedelta(seconds=settings.offline_timeout_sec)
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(DeviceState).where(DeviceState.online.is_(True),
                                      DeviceState.last_comm_at < cutoff))
        ).scalars()
        for st in rows:
            st.online = False
            await repo.raise_alarm(db, st.terminal_id, "offline",
                                   f"超过 {settings.offline_timeout_sec}s 无消息")
        # location-expired flag when last fix is stale but still marked located
        stale = (await db.execute(
            select(DeviceState).where(DeviceState.located.is_(True),
                                      DeviceState.located_at < cutoff))
        ).scalars()
        for st in stale:
            await repo.raise_alarm(db, st.terminal_id, "loc_expired",
                                   f"最后定位 {st.located_at}")
        await db.commit()
