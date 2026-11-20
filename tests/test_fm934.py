import struct

from gateway.protocol import fm934


def _ext(cmd: int, data: bytes) -> bytes:
    return struct.pack(">HH", len(data) + 2, cmd) + data


def test_battery_pct_and_voltage():
    payload = _ext(0x00A8, bytes([85])) + _ext(0x002D, struct.pack(">H", 14000))
    ext = fm934.parse_ext_payload(payload)
    assert ext.battery_pct == 85
    assert ext.ext_voltage_mv == 14000


def test_lbs():
    data = struct.pack(">HBHI", 460, 0, 0x262C, 0x04BA0102)
    ext = fm934.parse_ext_payload(_ext(0x00D8, data))
    assert ext.lbs.mcc == 460 and ext.lbs.cell_id == 0x04BA0102


def test_alarm_detached():
    # bit12 = 0 -> 拆除报警
    ext = fm934.parse_ext_payload(_ext(0x0089, struct.pack(">I", 0xFFFFEFFF)))
    assert ext.detached_alarm is True
    ext2 = fm934.parse_ext_payload(_ext(0x0089, struct.pack(">I", 0xFFFFFFFF)))
    assert ext2.detached_alarm is False


def test_imei_decode():
    imei = "863071067272666"
    hexstr = "".join(f"{ord(c):02x}" for c in imei)
    ext = fm934.parse_ext_payload(_ext(0x00D5, bytes.fromhex(hexstr)))
    assert ext.imei == imei


def test_mode_upload():
    ext = fm934.parse_ext_payload(_ext(0x002A, bytes([0]) + struct.pack(">I", 30)))
    assert ext.work_mode == 0 and ext.report_interval == 30
