from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class DeviceIn(BaseModel):
    asset_no: str
    terminal_id: str
    phone: str
    brand: str = ""
    model: str = ""
    serial_no: str = ""
    warehouse: str = ""
    site: str = ""
    owner: str = ""
    plate_color: int = 0
    plate: str = ""


class DeviceOut(DeviceIn):
    id: int
    bound_at: datetime
    unbound: bool

    class Config:
        from_attributes = True


class DeviceStateOut(BaseModel):
    terminal_id: str
    online: bool
    last_comm_at: Optional[datetime]
    lat: Optional[float]
    lng: Optional[float]
    altitude: Optional[float]
    speed: Optional[float]
    direction: Optional[int]
    located: bool
    located_at: Optional[datetime]
    loc_source: str
    external_power: bool
    battery_pct: Optional[int]
    charging: bool
    acc_on: bool
    work_mode: Optional[int]
    report_interval: Optional[int]
    iccid: str
    imei: str
    updated_at: datetime

    class Config:
        from_attributes = True


class LocationOut(BaseModel):
    terminal_id: str
    lat: float
    lng: float
    altitude: Optional[float]
    speed: float
    direction: int
    located: bool
    loc_source: str
    battery_pct: Optional[int]
    external_power: bool
    collected_at: datetime

    class Config:
        from_attributes = True


class AlarmOut(BaseModel):
    id: int
    terminal_id: str
    type: str
    level: str
    detail: str
    triggered_at: datetime
    recovered_at: Optional[datetime]
    acknowledged_at: Optional[datetime]
    active: bool

    class Config:
        from_attributes = True


class FenceIn(BaseModel):
    name: str
    site: str = ""
    shape_type: str = "circle"          # circle | polygon
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    radius_m: Optional[float] = None
    polygon: str = ""                   # GeoJSON polygon string
    buffer_m: float = 50.0
    devices: list[str] = []             # 空=全部设备;否则仅这些 terminal_id
    alert_on_enter: bool = True
    alert_on_leave: bool = True


class FenceOut(FenceIn):
    id: int
    enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_fence(cls, f) -> "FenceOut":
        import json
        d = {c.name: getattr(f, c.name) for c in f.__table__.columns
             if c.name not in {"devices"}}
        d["devices"] = json.loads(f.devices or "[]")
        return cls(**d)


class ParamSet(BaseModel):
    """8103 param items: {param_id_hex: value}. DWORD -> int, STRING -> str."""
    params: dict[str, str | int]


class TextDownlink(BaseModel):
    text: str
    flag: int = 0          # bit0 紧急


class OverviewOut(BaseModel):
    total: int
    online: int
    on_battery: int
    active_alarms: int
