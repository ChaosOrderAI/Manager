"""Codec round-trip tests using the spec's own examples."""
import pytest

from gateway.protocol.codec import (CodecError, FrameDecoder, Header, Message,
                                    checksum, decode_frame, encode, escape,
                                    unescape)


def test_escape_example_from_spec():
    # spec: 0x30 0x7e 0x08 0x7d 0x55 -> 0x7e 30 7d02 08 7d01 55 7e
    raw = bytes([0x30, 0x7e, 0x08, 0x7d, 0x55])
    assert escape(raw) == bytes([0x30, 0x7d, 0x02, 0x08, 0x7d, 0x01, 0x55])
    assert unescape(escape(raw)) == raw


def test_checksum_xor():
    assert checksum(bytes([0x01, 0x02, 0x03])) == 0x01 ^ 0x02 ^ 0x03


def _msg():
    h = Header(msg_id=0x0002, body_len=0, encrypt=0, subcontract=False,
               phone="013812345678", serial=7)
    return Message(h, b"")


def test_encode_decode_roundtrip():
    msg = _msg()
    frame = encode(msg)
    assert frame[0] == 0x7E and frame[-1] == 0x7E
    dec = decode_frame(frame)
    assert dec.header.msg_id == 0x0002
    assert dec.header.phone == "013812345678"
    assert dec.header.serial == 7
    assert dec.body == b""


def test_stream_decoder_two_frames_and_fragment():
    f = encode(_msg())
    dec = FrameDecoder()
    # split frame arbitrarily
    msgs = dec.feed(f[:5])
    assert msgs == []
    msgs = dec.feed(f[5:] + f)
    assert len(msgs) == 2


def test_bad_checksum_dropped():
    f = bytearray(encode(_msg()))
    f[-2] ^= 0xFF  # corrupt last byte before flag (escaped may differ; use decode_frame)
    # build an explicitly bad frame instead
    import gateway.protocol.codec as C
    raw = b"\x00\x02\x00\x00" + b"\x01" * 8 + b"\x00"  # payload+checksum(wrong)
    bad = bytes([0x7E]) + C.escape(raw) + bytes([0x7E])
    with pytest.raises(CodecError):
        decode_frame(bad)
