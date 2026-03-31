"""Minimal GGUF metadata reader — extracts context_length from model files.

GGUF format: little-endian, header = magic(4) + version(4) + tensor_count(8) + kv_count(8),
then kv_count sequential key-value pairs with variable-length encoding.
"""
import struct
from pathlib import Path

GGUF_MAGIC = 0x46554747  # "GGUF" as LE uint32

# Value type enum → struct format (None = variable length)
_VALUE_FORMATS = {
    0: "B",    # UINT8
    1: "b",    # INT8
    2: "<H",   # UINT16
    3: "<h",   # INT16
    4: "<I",   # UINT32
    5: "<i",   # INT32
    6: "<f",   # FLOAT32
    7: "B",    # BOOL
    8: None,   # STRING
    9: None,   # ARRAY
    10: "<Q",  # UINT64
    11: "<q",  # INT64
    12: "<d",  # FLOAT64
}


def _read_string(data: bytes, offset: int) -> tuple[str, int]:
    length = struct.unpack_from("<Q", data, offset)[0]
    offset += 8
    value = data[offset:offset + length].decode("utf-8", errors="replace")
    return value, offset + length


def _read_value(data: bytes, offset: int, vtype: int):
    fmt = _VALUE_FORMATS.get(vtype)
    if fmt is not None and vtype != 8 and vtype != 9:
        size = struct.calcsize(fmt)
        value = struct.unpack_from(fmt, data, offset)[0]
        return value, offset + size
    if vtype == 8:  # STRING
        return _read_string(data, offset)
    if vtype == 9:  # ARRAY
        elem_type = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        count = struct.unpack_from("<Q", data, offset)[0]
        offset += 8
        values = []
        for _ in range(count):
            v, offset = _read_value(data, offset, elem_type)
            values.append(v)
        return values, offset
    raise ValueError(f"Unknown GGUF value type: {vtype}")


def _skip_value(data: bytes, offset: int, vtype: int) -> int:
    """Skip past a value without fully parsing it (same traversal, discard result)."""
    _, offset = _read_value(data, offset, vtype)
    return offset


def read_context_length(model_path: str | Path) -> int | None:
    """Read the context_length from a GGUF file's metadata.

    Returns the integer context length, or None if not found.
    Reads only the header + metadata (typically <1MB), not the full file.
    """
    model_path = Path(model_path)
    if not model_path.exists():
        return None

    # Read enough for header + metadata (most metadata fits in first 1MB)
    # If not enough, fall back to reading more
    read_size = 1 * 1024 * 1024  # 1MB initial read
    with open(model_path, "rb") as f:
        data = f.read(read_size)

    if len(data) < 24:
        return None

    magic = struct.unpack_from("<I", data, 0)[0]
    if magic != GGUF_MAGIC:
        return None

    version = struct.unpack_from("<I", data, 4)[0]
    if version not in (2, 3):
        return None

    kv_count = struct.unpack_from("<Q", data, 16)[0]

    offset = 24
    for _ in range(kv_count):
        if offset >= len(data):
            # Need more data — read full metadata from file
            with open(model_path, "rb") as f:
                data = f.read(10 * 1024 * 1024)  # 10MB should be enough
            if offset >= len(data):
                return None

        key, offset = _read_string(data, offset)
        vtype = struct.unpack_from("<I", data, offset)[0]
        offset += 4

        if key.endswith(".context_length"):
            value, _ = _read_value(data, offset, vtype)
            return int(value)

        # Skip this value
        offset = _skip_value(data, offset, vtype)

    return None
