# M68 机器人租赁平台 · 基础版

按《M68S+FM934客户专用部标协议.doc》开发的 JT/T 808 接入平台，
覆盖基础版功能：**设备台账、终端绑定、实时定位、历史轨迹、电子围栏、
电源/通信告警、远程参数配置、下行指令**。

## 组成

```
m68-platform/
├── gateway/                  # TCP 接入服务(JT/T 808 + FM934 扩展)
│   ├── protocol/codec.py     # 0x7e 帧、转义、校验码、消息头编解码
│   ├── protocol/messages.py  # 标准消息解析/组包 (0100/0102/0200/8001/8103…)
│   ├── protocol/fm934.py     # 附录D 扩展指令 (电压/电量/基站/WiFi/IMEI…)
│   └── server/session.py     # 会话状态机: 注册→鉴权→心跳→位置→告警
├── app/                      # FastAPI 后台
│   ├── api/                  # devices/locations/alarms/fences/commands/overview
│   ├── models/entities.py    # SQLAlchemy 模型 (PostGIS 存位置)
│   └── services/             # 告警消抖、围栏判断、指令回执
├── web/                      # 前端(Leaflet 地图,定位总览/告警/围栏)
│   ├── index.html
│   ├── app.js                # 原生 JS,无构建步骤
│   └── nginx.conf            # 反代 /api 到 platform
├── alembic/                  # 数据库迁移
├── tools/simulator.py        # 模拟终端,无需真机即可联调
└── docker-compose.yml        # postgres+redis+platform+web 一键部署
```

## 快速开始

```bash
cd m68-platform
docker compose up -d --build          # postgres / redis / platform(API+TCP) / web
curl http://localhost:8000/health     # {"ok": true}
# 前端: http://localhost:8080
# 终端 TCP 接入: <server>:7808
# API 文档: http://localhost:8000/docs
```

### 无 Docker 本机运行（开发用 SQLite)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt aiosqlite
./run_local.sh                        # SQLite + 静态前端, http://localhost:8000
# 另开终端跑模拟器:
PYTHONPATH=. .venv/bin/python tools/simulator.py --count 5
```

本地开发前端：直接用 VS Code Live Server 或 `python -m http.server` 打开
`web/index.html`，把 `app.js` 顶部 `API = ''` 改成 `http://localhost:8000` 即可。

### 模拟终端联调（无真机）

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
PYTHONPATH=. python tools/simulator.py --count 5
```

### API 速览（Bearer token，见 `.env` 的 `API_TOKEN`)

```bash
TOKEN=change-me
# 登记设备
curl -X POST localhost:8000/api/devices -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"asset_no":"R001","terminal_id":"SIMTERM","phone":"013812345678"}'
# 实时位置总览(定位总览界面的数据源)
curl localhost:8000/api/overview/map -H "Authorization: Bearer $TOKEN"
# 历史轨迹
curl "localhost:8000/api/locations/SIMTERM/history?start=2026-11-18T00:00:00&end=2026-11-19T00:00:00" \
     -H "Authorization: Bearer $TOKEN"
# 建圆形围栏
curl -X POST localhost:8000/api/fences -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"name":"亦庄仓库","center_lat":39.79,"center_lng":116.5,"radius_m":500}'
# 下行: 改上报间隔为30s + 立即点名
curl -X POST localhost:8000/api/commands/SIMTERM/params \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"params":{"0x0001":30}}'
curl -X POST localhost:8000/api/commands/SIMTERM/locate -H "Authorization: Bearer $TOKEN"
```

## 协议覆盖情况

| 消息 | 状态 | 说明 |
|---|---|---|
| 0x0100 注册 / 0x8100 注册应答 | ✅ | 未知终端自动建档;车牌色=0 时按 VIN 处理 |
| 0x0102 鉴权 / 0x0002 心跳 | ✅ | 鉴权码校验、在线状态维护 |
| 0x0200 位置汇报 | ✅ | 报警位/状态位/经纬度/附加项;南纬西经自动转负 |
| 0x0001 / 0x8001 通用应答 | ✅ | 回执写 command_log 做指令追踪 |
| 0x8103/8104/0104 参数设置/查询 | ✅ | 表11 参数(DWORD/STRING)自动序列化 |
| 0x8105 终端控制 | ✅ | cmd=4 复位 |
| 0x8201/0201 位置查询 | ✅ | 平台点名 |
| 0x8300/6006 文本下发/上报 | ✅ | GBK 编解码 |
| 附录D 扩展(0x30 附加项) | ✅ | 0x0089/0x00C5 报警态、0x00D8 基站、0x00B9 WiFi、0x002D 电压、0x00A8 电量、0x00D5 IMEI、0x00B2 ICCID、0x002A 工作模式 |
| 分包(消息头 bit13) | ⚠️ 透传 | 帧层支持,应用层组包未做(终端目前未用) |
| RSA 加密(bit10) | ❌ | 协议保留位,M68S 未启用 |

## 告警映射(协议位 → 平台 type)

| 位 | 平台 type |
|---|---|
| 报警位 bit1 超速 | `overspeed` |
| 报警位 bit7 主电源欠压 | `low_voltage` |
| 报警位 bit8 声控 | `sound` |
| 扩展 0x0089 bit12 拆除 | `detached`(critical) |
| 扩展 0x00C5 bit6 振动 | `vibrate` |
| 电量 ≤20% | `low_battery` |
| TCP 断开 | `offline`(由超时检测任务补) |
| 围栏进出 | `fence_enter` / `fence_leave` |

## 与基础版方案的对照

方案第 7 章基础版功能 → 本项目接口:

- **设备台账与绑定** → `POST/GET /api/devices`、`unbind` 保留拆装历史
- **地图与轨迹** → `/api/overview/map` + `/api/locations/{id}/history`
- **电子围栏** → `/api/fences` 圆形/多边形 + 边界缓冲 + 进出事件
- **电源与通信告警** → `/api/alarms`,掉电/低电量/离线/位置过期
- **定位总览** → `/api/overview`(在线数、电池供电数、待处理告警)
- **远程配置** → `/api/commands/{id}/params`(上报周期/服务器地址/超速阈值等表11参数)

## 测试

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
```

17 项测试覆盖:转义/校验码(协议自带示例)、流式拆包、位置解析、
注册消息、参数组包、扩展指令解码、围栏判断。
