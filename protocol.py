import struct

MAX_MESSAGE_LENGTH = 1_000_000  # 1 MB Safety limit


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
    
    if length > MAX_MESSAGE_LENGTH:
        return None
        
    data = stream.read(length)
    if not data or len(data) < length:
        return None
    return data.decode("utf-8")
