import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import alarms, commands, devices, fences, locations, overview
from app.core.config import settings
from app.services.offline_watchdog import watchdog_loop
from gateway.server.tcp_server import run_gateway

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [asyncio.create_task(run_gateway()),
             asyncio.create_task(watchdog_loop())]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="M68 Robot Rental Platform (Basic)",
              version="1.0", lifespan=lifespan)

# 本地开发模式: /web 静态目录 + 根路径跳转到 index.html
from pathlib import Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_web = Path(__file__).resolve().parent.parent / "web"
if _web.is_dir():
    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(_web / "index.html")
    app.mount("/static", StaticFiles(directory=_web), name="static")

    @app.get("/app.js", include_in_schema=False)
    async def appjs():
        return FileResponse(_web / "app.js")

for r in (devices.router, locations.router, alarms.router, fences.router,
          commands.router, overview.router):
    app.include_router(r)


@app.get("/health")
async def health():
    return {"ok": True}
