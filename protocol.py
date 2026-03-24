import struct


def send_message(stream, message: str) -> None:
    encoded = message.encode("utf-8")
    stream.write(struct.pack(">I", len(encoded)))
    stream.write(encoded)
    if hasattr(stream, "flush"):
        stream.flush()


def recv_message(stream) -> str | None:
    header = stream.read(4)
    if not header or len(header) < 4:
        return None
    length = struct.unpack(">I", header)[0]
    data = stream.read(length)
    if not data or len(data) < length:
        return None
    return data.decode("utf-8")
