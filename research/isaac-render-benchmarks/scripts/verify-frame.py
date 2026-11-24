"""Check a newly captured 720p warehouse PNG against its capture receipt."""

import datetime as dt
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

IMAGE_ID = "sha256:2d4ebfef053f740b634e30723e38ed736255f677553425ef35552437d74c3b21"
GPU_NAME = "NVIDIA RTX PRO 6000 Blackwell Server Edition"
WAREHOUSE = "/Isaac/Environments/Simple_Warehouse/full_warehouse.usd"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def image_detail(data):
    require(data.startswith(PNG_MAGIC), "invalid PNG signature")
    pos = len(PNG_MAGIC)
    chunks = []
    header = None
    ended = False
    while pos + 12 <= len(data):
        size, kind = struct.unpack_from(">I4s", data, pos)
        stop = pos + 8 + size
        require(stop + 4 <= len(data), "truncated PNG chunk")
        chunk = data[pos + 8:stop]
        crc, = struct.unpack_from(">I", data, stop)
        require(zlib.crc32(kind + chunk) == crc, "invalid PNG chunk checksum")
        pos = stop + 4
        if kind == b"IHDR":
            require(header is None and size == 13, "invalid PNG header")
            header = struct.unpack(">IIBBBBB", chunk)
            width, height, depth, color, compression, filtering, interlace = header
            require((width, height, depth) == (1280, 720, 8), "expected 1280x720, 8-bit PNG")
            require(color in (2, 6) and not any((compression, filtering, interlace)), "expected noninterlaced RGB or RGBA")
        elif kind == b"IDAT":
            require(header is not None, "PNG data precedes header")
            chunks.append(chunk)
        elif kind == b"IEND":
            require(not chunk and pos == len(data), "invalid PNG ending")
            ended = True
            break
    require(header is not None and chunks and ended, "incomplete PNG")

    channels = 3 if color == 2 else 4
    stride = width * channels
    expected = height * (stride + 1)
    stream = zlib.decompressobj()
    scanlines = stream.decompress(b"".join(chunks), expected + 1)
    require(len(scanlines) == expected and stream.eof and not stream.unused_data, "invalid PNG pixel data")
    previous = bytearray(stride)
    colors = set()
    for y in range(height):
        offset = y * (stride + 1)
        mode = scanlines[offset]
        require(mode <= 4, "invalid PNG filter")
        row = bytearray(scanlines[offset + 1:offset + 1 + stride])
        if mode:
            for x in range(stride):
                left = row[x - channels] if x >= channels else 0
                up = previous[x]
                corner = previous[x - channels] if x >= channels else 0
                if mode == 1:
                    delta = left
                elif mode == 2:
                    delta = up
                elif mode == 3:
                    delta = (left + up) // 2
                else:
                    p = left + up - corner
                    delta = min((left, up, corner), key=lambda value: abs(p - value))
                row[x] = (row[x] + delta) & 255
        if y % 10 == 0:
            for x in range(0, stride, 10 * channels):
                if channels == 3 or row[x + 3] != 0:
                    colors.add(bytes(row[x:x + 3]))
        previous = row
    require(len(colors) >= 16, "warehouse frame is blank, transparent, or nearly uniform")
    return {"width": width, "height": height, "sampled_distinct_rgb": len(colors)}


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value)
    require(parsed.utcoffset() == dt.timedelta(0), "capture timestamp must be UTC")
    return parsed


def verify(image, receipt_path):
    require(image.is_file() and not image.is_symlink(), "missing regular frame")
    require(receipt_path.is_file() and not receipt_path.is_symlink(), "missing regular capture receipt")
    require(image.stat().st_size <= 8_000_000, "frame exceeds expected size")
    data = image.read_bytes()
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    digest = hashlib.sha256(data).hexdigest()
    require(receipt["image_id"] == IMAGE_ID, "unexpected Isaac Sim image")
    require(receipt["sim_version"] == "6.0.1", "unexpected Isaac Sim version")
    require(receipt["stage_url"].endswith(WAREHOUSE), "unexpected warehouse stage")
    require(receipt["stage_loaded"] is True, "stage load unverified")
    require(isinstance(receipt["warehouse_mesh_count"], int) and receipt["warehouse_mesh_count"] >= 1, "warehouse geometry absent")
    require(receipt["camera_path"].startswith("/") and receipt["render_product"].startswith("/"), "camera or render product absent")
    require(receipt["render_device"] == GPU_NAME, "expected exactly one visible RTX PRO 6000 Blackwell Server Edition GPU")
    require(receipt["render_mode"] == "RealTimePathTracing", "unexpected baseline render mode")
    require(receipt["capture_completed"] is True and receipt["frame_sha256"] == digest, "capture receipt does not match the frame")
    started = timestamp(receipt["capture_started_utc"])
    completed = timestamp(receipt["capture_completed_utc"])
    now = dt.datetime.now(dt.UTC)
    require(started <= completed <= now + dt.timedelta(seconds=5), "invalid capture chronology")
    return {
        "status": "verified",
        **image_detail(data),
        "frame_sha256": digest,
        "capture_receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "capture_completed_utc": receipt["capture_completed_utc"],
        "verified_utc": now.isoformat(),
    }


if __name__ == "__main__":
    try:
        result = verify(Path(sys.argv[1]), Path(sys.argv[2]))
    except (IndexError, KeyError, OSError, TypeError, ValueError, struct.error, zlib.error) as exc:
        print(f"frame verification failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result, sort_keys=True))
