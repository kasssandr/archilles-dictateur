import struct
import io
from protocol import send_message, recv_message


def test_send_message_prepends_length():
    buf = io.BytesIO()
    send_message(buf, "START")
    buf.seek(0)
    length = struct.unpack(">I", buf.read(4))[0]
    payload = buf.read(length).decode("utf-8")
    assert length == 5
    assert payload == "START"


def test_recv_message_reads_length_prefixed():
    buf = io.BytesIO()
    msg = "RESULT:Hallo Welt"
    encoded = msg.encode("utf-8")
    buf.write(struct.pack(">I", len(encoded)))
    buf.write(encoded)
    buf.seek(0)
    result = recv_message(buf)
    assert result == "RESULT:Hallo Welt"


def test_roundtrip_with_newlines():
    buf = io.BytesIO()
    msg = "RESULT:Zeile eins\nZeile zwei\nZeile drei"
    send_message(buf, msg)
    buf.seek(0)
    result = recv_message(buf)
    assert result == msg


def test_recv_message_empty_stream_returns_none():
    buf = io.BytesIO(b"")
    result = recv_message(buf)
    assert result is None
