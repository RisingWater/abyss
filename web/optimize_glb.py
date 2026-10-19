# -*- coding: utf-8 -*-
"""GLB 轻量优化：把内嵌大图换成降采样 JPEG，并整体重排 bufferView。
只改贴图，不动几何，避免量化带来的画质/兼容风险。
用法: python3 optimize_glb.py <in.glb> <out.glb> [max_edge] [quality]
"""
import io
import json
import struct
import sys

from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
max_edge = int(sys.argv[3]) if len(sys.argv) > 3 else 2048
quality = int(sys.argv[4]) if len(sys.argv) > 4 else 88

with open(src, "rb") as f:
    data = f.read()
magic, ver, total = struct.unpack("<III", data[:12])
assert magic == 0x46546C67, "not a glb"

off, js, bs, bjs, bbs = 12, None, None, 0, 0
while off < len(data):
    clen, ctype = struct.unpack("<II", data[off:off + 8])
    body = data[off + 8:off + 8 + clen]
    if ctype == 0x4E4F534A:
        js, bjs = body, clen
    elif ctype == 0x4E4942:
        bs, bbs = body, clen
    off += 8 + clen

gltf = json.loads(js)
bviews = gltf["bufferViews"]


def pad4(n):
    return (4 - n % 4) % 4


# 1) 生成压缩后的贴图字节
img_repl = {}
for i, im in enumerate(gltf.get("images", [])):
    bv = bviews[im["bufferView"]]
    raw = bs[bv.get("byteOffset", 0):bv.get("byteOffset", 0) + bv["byteLength"]]
    pic = Image.open(io.BytesIO(raw)).convert("RGB")
    before = pic.size
    scale = min(1.0, max_edge / max(pic.size))
    if scale < 1.0:
        pic = pic.resize((max(1, int(pic.width * scale)), max(1, int(pic.height * scale))),
                         Image.LANCZOS)
    buf = io.BytesIO()
    pic.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
    img_repl[im["bufferView"]] = buf.getvalue()
    im["mimeType"] = "image/jpeg"
    print("image %d: %s %d bytes -> %s %d bytes"
          % (i, before, len(raw), pic.size, len(img_repl[im["bufferView"]])))

# 2) 顺序重排所有 bufferView（保持原顺序，重算偏移与 4 字节对齐）
pieces, new_views, cursor = [], [], 0
for idx, bv in enumerate(bviews):
    src_off = bv.get("byteOffset", 0)
    src_len = bv["byteLength"]
    payload = img_repl.get(idx, bs[src_off:src_off + src_len])
    buf_i = bv.get("buffer", 0)
    if buf_i != 0:
        raise SystemExit("多 buffer 的 GLB 未处理")
    new_views.append({
        "buffer": 0,
        "byteOffset": cursor,
        "byteLength": len(payload),
    })
    if "byteStride" in bv:
        new_views[-1]["byteStride"] = bv["byteStride"]
    if "target" in bv:
        new_views[-1]["target"] = bv["target"]
    pieces.append(payload)
    cursor += len(payload)
    cursor += pad4(cursor)

gltf["bufferViews"] = new_views
gltf["buffers"][0]["byteLength"] = cursor

# bufferView 索引在 images/materials 里的引用不变，仅偏移变化
new_bin = bytearray()
for p in pieces:
    new_bin += p
    new_bin += b"\x00" * pad4(len(p))

# 3) 打包 GLB
json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
json_bytes += b" " * pad4(len(json_bytes))
bin_bytes = bytes(new_bin)
bin_bytes += b"\x00" * pad4(len(bin_bytes))

out = bytearray()
out += struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(json_bytes) + 8 + len(bin_bytes))
out += struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
out += struct.pack("<II", len(bin_bytes), 0x4E4942) + bin_bytes

with open(dst, "wb") as f:
    f.write(out)

print("written %s : %d -> %d bytes (%.1f%%)"
      % (dst, len(data), len(out), len(out) / len(data) * 100))