from datetime import datetime
from sqlalchemy import (BigInteger, Boolean, DateTime, Float, ForeignKey,
                        Integer, String, Text, Index)
from sqlalchemy.orm import Mapped, mapped_column
from geoalchemy2 import Geography
from sqlalchemy import BigInteger as _BI

from app.models.db import Base

# SQLite has no real autoincrement on BigInteger PK — use INTEGER there.
_BigIntPk = _BI().with_variant(Integer, "sqlite")


class Device(Base):
    """设备台账 + 终端绑定."""
    __tablename__ = "device"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    brand: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    serial_no: Mapped[str] = mapped_column(String(64), default="")  # 厂商序列号
    warehouse: Mapped[str] = mapped_column(String(128), default="")
    site: Mapped[str] = mapped_column(String(128), default="")
    owner: Mapped[str] = mapped_column(String(64), default="")

    terminal_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    plate_color: Mapped[int] = mapped_column(Integer, default=0)
    plate: Mapped[str] = mapped_column(String(32), default="")  # or VIN
    manufacturer: Mapped[str] = mapped_column(String(16), default="")
    auth_code: Mapped[str] = mapped_column(String(64), default="")
    bound_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    unbound: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DeviceState(Base):
    """最新状态(位置/电源/在线),一台设备一行."""
    __tablename__ = "device_state"

    terminal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    last_comm_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    lat: Mapped[float] = mapped_column(Float, nullable=True)
    lng: Mapped[float] = mapped_column(Float, nullable=True)
    altitude: Mapped[float] = mapped_column(Float, nullable=True)
    speed: Mapped[float] = mapped_column(Float, nullable=True)
    direction: Mapped[int] = mapped_column(Integer, nullable=True)
    located_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    located: Mapped[bool] = mapped_column(Boolean, default=False)
    loc_source: Mapped[str] = mapped_column(String(16), default="")  # gnss/lbs/wifi/last

    external_power: Mapped[bool] = mapped_column(Boolean, default=True)
    battery_pct: Mapped[int] = mapped_column(Integer, nullable=True)
    ext_voltage_mv: Mapped[int] = mapped_column(Integer, nullable=True)
    charging: Mapped[bool] = mapped_column(Boolean, default=False)

    acc_on: Mapped[bool] = mapped_column(Boolean, default=False)
    work_mode: Mapped[int] = mapped_column(Integer, nullable=True)
    report_interval: Mapped[int] = mapped_column(Integer, nullable=True)
    alarm_bits: Mapped[int] = mapped_column(BigInteger, default=0)
    status_bits: Mapped[int] = mapped_column(BigInteger, default=0)
    iccid: Mapped[str] = mapped_column(String(24), default="")
    imei: Mapped[str] = mapped_column(String(24), default="")
    product_id: Mapped[str] = mapped_column(String(40), default="")  # FM934 0x00A3

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LocationRecord(Base):
    """轨迹原始记录."""
    __tablename__ = "location_record"

    id: Mapped[int] = mapped_column(_BigIntPk, primary_key=True, autoincrement=True)
    terminal_id: Mapped[str] = mapped_column(String(64), index=True)
    msg_serial: Mapped[int] = mapped_column(Integer)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    altitude: Mapped[float] = mapped_column(Float, nullable=True)
    speed: Mapped[float] = mapped_column(Float)
    direction: Mapped[int] = mapped_column(Integer)
    located: Mapped[bool] = mapped_column(Boolean)
    loc_source: Mapped[str] = mapped_column(String(16), default="gnss")
    alarm_bits: Mapped[int] = mapped_column(BigInteger, default=0)
    status_bits: Mapped[int] = mapped_column(BigInteger, default=0)
    battery_pct: Mapped[int] = mapped_column(Integer, nullable=True)
    external_power: Mapped[bool] = mapped_column(Boolean, default=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # PostGIS geography on PG; plain text "lng,lat" on SQLite so the dev
    # profile runs without spatial extensions. management=False stops
    # geoalchemy2 from emitting CreateSpatialIndex DDL on sqlite.
    geom = mapped_column(
        Geography("POINT", srid=4326, spatial_index=False)
        .with_variant(Text, "sqlite"),
        nullable=True)

    __table_args__ = (
        Index("ix_loc_terminal_time", "terminal_id", "collected_at"),
        Index("uq_loc_terminal_serial", "terminal_id", "msg_serial",
              "collected_at", unique=True),
    )


class Alarm(Base):
    __tablename__ = "alarm"

    id: Mapped[int] = mapped_column(_BigIntPk, primary_key=True, autoincrement=True)
    terminal_id: Mapped[str] = mapped_column(String(64), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    # power_loss / low_battery / offline / loc_expired / detached / vibrate /
    # overspeed / fence_enter / fence_leave / charge_abnormal / sound
    level: Mapped[str] = mapped_column(String(16), default="warn")
    detail: Mapped[str] = mapped_column(Text, default="")
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    recovered_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    ack_by: Mapped[str] = mapped_column(String(64), default="")
    closed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Fence(Base):
    __tablename__ = "fence"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    site: Mapped[str] = mapped_column(String(128), default="")
    # GeoJSON polygon as text, or circle center+radius
    shape_type: Mapped[str] = mapped_column(String(16), default="circle")
    center_lat: Mapped[float] = mapped_column(Float, nullable=True)
    center_lng: Mapped[float] = mapped_column(Float, nullable=True)
    radius_m: Mapped[float] = mapped_column(Float, nullable=True)
    polygon: Mapped[str] = mapped_column(Text, default="")  # GeoJSON
    buffer_m: Mapped[float] = mapped_column(Float, default=50.0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # empty -> applies to all devices; otherwise only bound terminal_ids
    devices: Mapped[str] = mapped_column(Text, default="")  # JSON list
    alert_on_enter: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_on_leave: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FenceEvent(Base):
    __tablename__ = "fence_event"

    id: Mapped[int] = mapped_column(_BigIntPk, primary_key=True, autoincrement=True)
    fence_id: Mapped[int] = mapped_column(ForeignKey("fence.id"), index=True)
    terminal_id: Mapped[str] = mapped_column(String(64), index=True)
    event: Mapped[str] = mapped_column(String(8))  # enter / leave
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    happened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CommandLog(Base):
    """下行指令与回执."""
    __tablename__ = "command_log"

    id: Mapped[int] = mapped_column(_BigIntPk, primary_key=True, autoincrement=True)
    terminal_id: Mapped[str] = mapped_column(String(64), index=True)
    msg_id: Mapped[int] = mapped_column(Integer)
    serial: Mapped[int] = mapped_column(Integer)
    payload: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(16), default="sent", index=True)
    # pending -> sent -> acked | failed ; serial=0 表示排队未发
    ack_result: Mapped[int] = mapped_column(Integer, nullable=True)  # 0 ok...
    acked_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
