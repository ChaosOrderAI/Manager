"""Geofence evaluation: circle & polygon, enter/leave edge detection."""
from __future__ import annotations

import json
import math
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Fence, FenceEvent

EARTH_R = 6371000.0


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def _point_in_polygon(lat: float, lng: float, coords: list) -> bool:
    """Ray casting; coords = [[lng, lat], ...] single ring."""
    inside = False
    n = len(coords)
    j = n - 1
    for i in range(n):
        xi, yi = coords[i]  # lng, lat
        xj, yj = coords[j]
        if ((yi > lat) != (yj > lat)) and \
           (lng < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def inside_fence(f: Fence, lat: float, lng: float) -> bool:
    if f.shape_type == "circle" and f.center_lat is not None:
        return haversine_m(lat, lng, f.center_lat, f.center_lng) <= \
            (f.radius_m or 0) + f.buffer_m
    if f.shape_type == "polygon" and f.polygon:
        try:
            coords = json.loads(f.polygon)[0]  # GeoJSON Polygon->[ring]
            return _point_in_polygon(lat, lng, coords)
        except Exception:
            return False
    return False


class FenceChecker:
    """Remembers inside/outside state per (fence, terminal) to emit edges.
    Fence list is cached for `ttl` seconds to avoid a full table scan
    per location report."""

    def __init__(self, ttl: float = 30.0):
        self._inside: dict[tuple[int, str], bool] = {}
        self._fences: list = []
        self._fences_at: float = 0.0
        self._ttl = ttl

    async def _load_fences(self, db: AsyncSession) -> list:
        import time
        now = time.monotonic()
        if now - self._fences_at > self._ttl:
            self._fences = (await db.execute(
                select(Fence).where(Fence.enabled.is_(True)))).scalars().all()
            self._fences_at = now
        return self._fences

    async def warm(self, db: AsyncSession):
        """Re-seed inside-state from last known positions after restart,
        so a device already outside a fence still alarms correctly."""
        from app.models.entities import DeviceState
        states = (await db.execute(
            select(DeviceState).where(DeviceState.located.is_(True)))
        ).scalars().all()
        for st in states:
            for f in await self._load_fences(db):
                bound = json.loads(f.devices or "[]")
                if bound and st.terminal_id not in bound:
                    continue
                if st.lat is not None:
                    self._inside[(f.id, st.terminal_id)] = inside_fence(
                        f, st.lat, st.lng)

    async def evaluate(self, db: AsyncSession, terminal_id: str,
                       lat: float, lng: float) -> list[FenceEvent]:
        fences = await self._load_fences(db)
        events: list[FenceEvent] = []
        for f in fences:
            bound = json.loads(f.devices or "[]")
            if bound and terminal_id not in bound:
                continue
            inside = inside_fence(f, lat, lng)
            key = (f.id, terminal_id)
            prev = self._inside.get(key)
            if prev is None:
                self._inside[key] = inside
                continue
            if inside != prev:
                kind = "enter" if inside else "leave"
                ev = FenceEvent(fence_id=f.id, terminal_id=terminal_id,
                                event=kind, lat=lat, lng=lng)
                db.add(ev)
                if (kind == "enter" and f.alert_on_enter) or \
                   (kind == "leave" and f.alert_on_leave):
                    ev._fence = f
                    events.append(ev)
                self._inside[key] = inside
        return events
