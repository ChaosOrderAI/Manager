"""TCP session: JT/T 808 state machine for M68S+FM934 terminals."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

_UTC8 = timedelta(hours=8)
def _now_bj() -> datetime: return datetime.utcnow() + _UTC8
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from gateway.protocol import fm934, messages as M
from gateway.protocol.codec import (CodecError, FrameDecoder, Header, Message,
                                    encode)
from app.models.db import SessionLocal
from app.models.entities import Alarm
from app.services import repository as repo
from app.services.fence import FenceChecker

log = logging.getLogger("gateway.session")

# platform-side per-connection serial, wraps at 0xFFFF
class SerialGen:
    def __init__(self):
        self.v = 0
    def next(self) -> int:
        self.v = (self.v + 1) & 0xFFFF
        return self.v


class Session:
    def __init__(self, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter, fence_checker: FenceChecker,
                 server=None):
        self.reader, self.writer = reader, writer
        self.decoder = FrameDecoder()
        self.serial = SerialGen()
        self.fences = fence_checker
        self.server = server          # GatewayServer for session registry
        self.phone: Optional[str] = None
        self.terminal_id: Optional[str] = None
        self.authed = False
        self.peer = writer.get_extra_info("peername")

    async def run(self):
        log.info("conn from %s", self.peer)
        try:
            while True:
                data = await self.reader.read(4096)
                if not data:
                    break
                log.info("rx raw len=%d hex=%s", len(data), data.hex())
                for msg in self.decoder.feed(data):
                    await self._handle(msg)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            await self._mark_offline()
            if self.server:
                self.server.unregister(self)
            self.writer.close()

    # ---------- send ----------
    async def send(self, msg: Message):
        self.writer.write(encode(msg))
        await self.writer.drain()

    async def reply(self, req: Message, result: int = 0):
        await self.send(M.build_8001(req.header.serial, req.header.msg_id,
                                     result, req.header.phone,
                                     self.serial.next()))

    # ---------- dispatch ----------
    async def _handle(self, msg: Message):
        mid = msg.header.msg_id
        self.phone = msg.header.phone
        # 注册/鉴权前不入 server.sessions,防止冒充抢占会话槽
        async with SessionLocal() as db:
            try:
                if mid == 0x0100:
                    await self._on_register(db, msg)
                elif mid == 0x0102:
                    await self._on_auth(db, msg)
                elif not self.authed:
                    # 注册或鉴权前先拒绝业务消息
                    await self.reply(msg, 1)
                    return
                elif mid == 0x0002:
                    await self._on_heartbeat(db, msg)
                elif mid == 0x0001:
                    await self._on_term_reply(db, msg)
                elif mid == 0x0200:
                    await self._on_location(db, msg)
                elif mid == 0x0201:
                    await self._on_location_query_reply(db, msg)
                elif mid == 0x0003:
                    await self._on_logout(db, msg)
                elif mid == 0x0104:
                    await self._on_param_reply(db, msg)
                elif mid == 0x6006:
                    await self._on_text(db, msg)
                else:
                    await self.reply(msg, 3)  # unsupported
                # handler 内已 commit 关键路径,这里兜底提交残余状态
                try:
                    await db.commit()
                except Exception:
                    pass
            except Exception:
                log.exception("handle 0x%04x failed", mid)
                await db.rollback()
                try:
                    await self.reply(msg, 1)
                except Exception:
                    pass

    # ---------- handlers ----------
    async def _on_register(self, db: AsyncSession, msg: Message):
        log.info("0100 raw body len=%d hex=%s", len(msg.body), msg.body.hex())
        reg = M.parse_0100(msg.body)
        log.info("0100 parsed model=%r tid=%r plate=%r color=%d",
                 reg.model, reg.terminal_id, reg.plate, reg.plate_color)
        dev = await repo.device_by_phone(db, msg.header.phone)
        if dev is None:
            dev = await repo.device_by_terminal(db, reg.terminal_id)
        if dev is None:
            dev = await self._auto_provision(db, reg, msg.header.phone)
        dev.plate_color, dev.plate = reg.plate_color, reg.plate
        dev.manufacturer = reg.manufacturer
        dev.auth_code = f"{dev.terminal_id}-{dev.asset_no}"[:60]
        self.terminal_id = dev.terminal_id
        # 注册成功也视为已认证(协议允许直接进业务)
        self.authed = True
        if self.server:
            self.server.register(self)
        await self.send(M.build_8100(msg.header.serial, 0, dev.auth_code,
                                     msg.header.phone, self.serial.next()))
        log.info("registered %s -> terminal %s", msg.header.phone,
                 dev.terminal_id)
        await self._flush_pending(db, dev.terminal_id)

    async def _auto_provision(self, db: AsyncSession, reg, phone):
        """Minimal auto-enroll; asset_no defaults to terminal_id."""
        from app.models.entities import Device
        dev = Device(asset_no=reg.terminal_id or phone,
                     serial_no=reg.terminal_id, brand=reg.manufacturer,
                     model=reg.model, terminal_id=reg.terminal_id or phone,
                     phone=phone)
        db.add(dev)
        await db.flush()
        return dev

    async def _on_auth(self, db: AsyncSession, msg: Message):
        code = M.parse_0102(msg.body)
        dev = await repo.device_by_phone(db, msg.header.phone)
        # auth_code 必须存在且匹配;空 code 不允许通过
        ok = (dev is not None and bool(dev.auth_code)
              and dev.auth_code == code)
        self.authed = ok
        if ok and dev:
            self.terminal_id = dev.terminal_id
            st = await repo.get_state(db, dev.terminal_id)
            st.online = True
            st.last_comm_at = _now_bj()
            if self.server:
                self.server.register(self)      # 鉴权通过才入会话表
        await self.reply(msg, 0 if ok else 1)
        if ok and dev:
            await self._flush_pending(db, dev.terminal_id)

    async def _on_heartbeat(self, db: AsyncSession, msg: Message):
        # 心跳只证明连接活着,鉴权失败时不再更新 online 状态
        await self._touch(db, msg.header.phone)
        await self.reply(msg, 0)

    async def _on_term_reply(self, db: AsyncSession, msg: Message):
        r = M.parse_0001(msg.body)
        tid = await self._tid(db, msg.header.phone)
        if tid:
            await repo.ack_command(db, tid, r.reply_serial, r.reply_id,
                                   r.result)
        # no platform reply needed for 0x0001

    async def _on_location(self, db: AsyncSession, msg: Message):
        loc = M.parse_0200(msg.body)
        # 设备 BCD 时间就是 UTC+8;DB 全表口径统一为 naive UTC+8
        loc._serial = msg.header.serial
        tid = await self._tid(db, msg.header.phone)
        if not tid:
            await self.reply(msg, 2)
            return
        ext = self._extract_ext(loc)
        log.info("loc tid=%r product_id=%r authed=%s", tid, ext.product_id,
                 self.authed)
        # 出厂 tid='0000000' 的设备,用 0x00A3 product_id 升级成正式 ID
        # product_id 是设备固化串,与当前 tid 不同时就升级(幂等)
        if ext.product_id and tid != ext.product_id:
            new_tid = await self._upgrade_tid(db, msg.header.phone,
                                              ext.product_id)
            if new_tid:
                tid = new_tid
                self.terminal_id = new_tid
        st = await repo.get_state(db, tid)
        await repo.save_location(db, st, loc=loc, source=self._source(loc),
                                 battery_pct=ext.battery_pct,
                                 external=self._external(loc, ext))
        st.online = True
        st.last_comm_at = _now_bj()
        self._apply_ext_state(st, ext)
        await self._alarm_check(db, tid, loc, ext)
        if loc.positioned:
            try:
                events = await self.fences.evaluate(db, tid, loc.lat, loc.lng)
            except Exception:
                log.exception("fence evaluate failed tid=%s", tid)
                events = []
            for ev in events:
                fname = getattr(getattr(ev, "_fence", None), "name",
                                str(ev.fence_id))
                await repo.raise_alarm(
                    db, tid, f"fence_{ev.event}",
                    detail=f"{fname}: {'进入' if ev.event=='enter' else '离开'}",
                    level="info")
        # 先落库再回执,避免 socket 失败连带回滚位置数据
        await db.commit()
        await self.reply(msg, 0)

    async def _on_location_query_reply(self, db: AsyncSession, msg: Message):
        r = M.parse_0201(msg.body)
        r.location._serial = msg.header.serial
        tid = await self._tid(db, msg.header.phone)
        if tid:
            st = await repo.get_state(db, tid)
            ext = self._extract_ext(r.location)
            await repo.save_location(db, st, loc=r.location,
                                     source=self._source(r.location),
                                     battery_pct=ext.battery_pct,
                                     external=self._external(r.location, ext))
        await self.reply(msg, 0)

    async def _on_logout(self, db: AsyncSession, msg: Message):
        tid = await self._tid(db, msg.header.phone)
        if tid:
            st = await repo.get_state(db, tid)
            st.online = False
        await self.reply(msg, 0)

    async def _on_param_reply(self, db: AsyncSession, msg: Message):
        M.parse_0104(msg.body)
        await self.reply(msg, 0)

    async def _on_text(self, db: AsyncSession, msg: Message):
        enc, text = M.parse_6006(msg.body)
        log.info("text from %s: %s", msg.header.phone, text)
        await self.reply(msg, 0)

    # ---------- helpers ----------
    async def _tid(self, db, phone) -> Optional[str]:
        if self.terminal_id:
            return self.terminal_id
        dev = await repo.device_by_phone(db, phone)
        self.terminal_id = dev.terminal_id if dev else None
        return self.terminal_id

    async def _touch(self, db, phone):
        tid = await self._tid(db, phone)
        if tid:
            st = await repo.get_state(db, tid)
            st.online = True
            st.last_comm_at = _now_bj()

    @staticmethod
    def _extract_ext(loc) -> fm934.ExtData:
        # FM934 的扩展项在附加 id 0xEB 下,内容是多个 WORD len|WORD cmd|data
        # 串联.0x30 在标准协议里已被占用(信号强度等),不能当 FM934 容器解.
        merged = fm934.ExtData()
        for blob in loc.extras.get(0xEB, []):
            sub = fm934.parse_ext_payload(blob)
            for f in vars(sub):
                v = getattr(sub, f)
                if v not in (None, [], ""):
                    setattr(merged, f, v)
        return merged

    @staticmethod
    def _source(loc) -> str:
        if loc.positioned:
            return "gnss"
        has_ext = bool(loc.extras.get(0x30) or loc.extras.get(0xEB))
        return "lbs" if has_ext else "last"

    @staticmethod
    def _external(loc, ext) -> bool:
        if ext.ext_voltage_mv:
            return ext.ext_voltage_mv > 5000
        return True  # unknown -> assume powered; device reports charging state otherwise

    async def _flush_pending(self, db: AsyncSession, terminal_id: str):
        """设备连上后,把队列里的 pending 命令按序发出去."""
        try:
            from app.api.commands import flush_pending
            n = await flush_pending(db, terminal_id, self)
            if n:
                log.info("flushed %d pending cmd(s) to %s", n, terminal_id)
        except Exception:
            log.exception("flush pending failed tid=%s", terminal_id)

    async def _upgrade_tid(self, db, phone: str, new_tid: str) -> Optional[str]:
        """Device.terminal_id 是 '0000000' 时,用 product_id/IMEI 替换;同时迁移
        DeviceState/LocationRecord 上的外键,避免历史轨迹孤儿。"""
        from sqlalchemy import select, update
        from app.models.entities import Device, DeviceState, LocationRecord
        dev = (await db.execute(
            select(Device).where(Device.phone == phone))).scalar_one_or_none()
        if not dev or dev.terminal_id == new_tid:
            return None
        old = dev.terminal_id
        # 若已有正式 tid 的设备存在(不该发生),不覆盖
        exists = (await db.execute(
            select(Device).where(Device.terminal_id == new_tid))
        ).scalar_one_or_none()
        if exists and exists.id != dev.id:
            log.warning("tid upgrade conflict %s -> %s, existing dev id=%d",
                        old, new_tid, exists.id)
            return None
        dev.terminal_id = new_tid
        dev.asset_no = new_tid
        if dev.auth_code.startswith(old):
            dev.auth_code = f"{new_tid}-{new_tid}"[:60]
        await db.execute(
            update(DeviceState).where(DeviceState.terminal_id == old)
            .values(terminal_id=new_tid))
        await db.execute(
            update(LocationRecord).where(LocationRecord.terminal_id == old)
            .values(terminal_id=new_tid))
        log.info("tid upgrade phone=%s %s -> %s", phone, old, new_tid)
        return new_tid

    @staticmethod
    def _apply_ext_state(st, ext: fm934.ExtData):
        if ext.iccid: st.iccid = ext.iccid
        if ext.imei: st.imei = ext.imei
        if ext.product_id: st.product_id = ext.product_id
        if ext.battery_pct is not None: st.battery_pct = ext.battery_pct
        if ext.ext_voltage_mv: st.ext_voltage_mv = ext.ext_voltage_mv
        if ext.work_mode is not None: st.work_mode = ext.work_mode
        if ext.report_interval is not None:
            st.report_interval = ext.report_interval

    async def _alarm_check(self, db, tid, loc, ext):
        # bit1 overspeed, bit7 low main-power, bit8 sound alarm
        if loc.alarm & (1 << 1):
            await repo.raise_alarm(db, tid, "overspeed", "超速报警")
        else:
            await repo.resolve_alarm(db, tid, "overspeed")
        if loc.alarm & (1 << 7):
            await repo.raise_alarm(db, tid, "low_voltage", "终端主电源欠压")
        else:
            await repo.resolve_alarm(db, tid, "low_voltage")
        if loc.alarm & (1 << 8):
            await repo.raise_alarm(db, tid, "sound", "声控录音报警")
        if ext.detached_alarm:
            await repo.raise_alarm(db, tid, "detached", "拆除报警",
                                   level="critical")
        if ext.vibrate_alarm:
            await repo.raise_alarm(db, tid, "vibrate", "振动报警")
        if ext.battery_pct is not None and ext.battery_pct <= 20:
            await repo.raise_alarm(db, tid, "low_battery",
                                   f"电量 {ext.battery_pct}%")
        elif ext.battery_pct is not None:
            await repo.resolve_alarm(db, tid, "low_battery")

    async def _mark_offline(self):
        # 不立即置 offline:追踪型终端常态就是"打点-断开-休眠-再连",
        # 断开只说明 TCP 关了. 真正的"离线"由 watchdog 按 last_comm_at 超时判定.
        # 这里只把连接从 sessions 表里拿掉 (在 run() finally 里做).
        return
