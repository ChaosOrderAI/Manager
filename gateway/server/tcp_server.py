"""Async TCP server accepting M68S+FM934 terminals."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from gateway.server.session import Session
from app.services.fence import FenceChecker
from app.core.config import settings

log = logging.getLogger("gateway")


class GatewayServer:
    """Holds live sessions so the API layer can push downlink commands."""

    def __init__(self):
        self.fence_checker = FenceChecker()
        self.sessions: dict[str, Session] = {}   # phone -> session

    def register(self, s: Session):
        if s.phone:
            self.sessions[s.phone] = s

    def unregister(self, s: Session):
        if s.phone and self.sessions.get(s.phone) is s:
            del self.sessions[s.phone]

    def session_for(self, phone: str) -> Optional[Session]:
        return self.sessions.get(phone)


server = GatewayServer()


async def _on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    s = Session(reader, writer, server.fence_checker, server)
    await s.run()


async def run_gateway():
    # 重启后用最后位置恢复 inside 状态,避免漏报已在围栏外的设备
    try:
        from app.models.db import SessionLocal
        async with SessionLocal() as db:
            await server.fence_checker.warm(db)
    except Exception:
        log.exception("fence state warm-up failed")

    srv = await asyncio.start_server(
        _on_client, settings.gateway_host, settings.gateway_port)
    log.info("JT/T808 gateway listening on %s:%s",
             settings.gateway_host, settings.gateway_port)
    async with srv:
        await srv.serve_forever()
