"""Test the adaptive model-length parsing in parse_0100."""
import struct

from gateway.protocol import messages as M


def _build(model_len: int):
    return (struct.pack(">HH", 11, 1101)
            + b"12345"
            + b"M68S" + b"\x00" * (model_len - 4)
            + b"TERM001"
            + bytes([1])
            + "京A12345".encode("gbk"))


def test_parse_20byte_model():
    """FM934 errata layout: model is always 20 bytes."""
    reg = M.parse_0100(_build(20))
    assert reg.model == "M68S"
    assert reg.terminal_id == "TERM001"
    assert reg.plate_color == 1
    assert reg.plate == "京A12345"


def test_parse_short_body_falls_back_to_8byte():
    """Standard JT/T 808 layout (model=8B) only when the body is too
    short to hold the 20-byte FM934 model — a defensive fallback."""
    # 8B model + 7B tid + 1B color + 3B plate = 24 < 28
    body = (struct.pack(">HH", 11, 1101) + b"12345"
            + b"M68S" + b"\x00" * 4 + b"TERM001" + bytes([1]) + b"ABC")
    reg = M.parse_0100(body)
    assert reg.model == "M68S"
    assert reg.terminal_id == "TERM001"
