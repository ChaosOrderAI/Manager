#!/usr/bin/env bash
# 本地无 docker 启动: SQLite + 内置静态前端
set -e
cd "$(dirname "$0")"
export DATABASE_URL="sqlite+aiosqlite:///./m68.db"
export API_TOKEN="${API_TOKEN:-change-me}"
.venv/bin/python -c "
import asyncio
from app.models.db import engine, Base
from app.models import entities
async def m():
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
asyncio.run(m())
print('db ready')"
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
