# -*- coding: utf-8 -*-
"""GLB 网格简化：顶点聚类（vertex clustering），生成低模版本。

原理：把模型空间用三维体素（voxel）划分，同一体素内的顶点合并成一个顶点，
再重建索引并丢弃退化三角形。通过调节体素分辨率控制目标面数。

UV 处理：聚类键里加入量化后的 (u, v)，这样同一簇内 UV 完全一致，
不会出现「顶点合并后贴图渗色」。代价是簇数略增，但面数仍由体素分辨率主导。

用法：
    python3 simplify_glb.py <in.glb> <out.glb> --target 50000
    python3 simplify_glb.py <in.glb> <out.glb> --target 50000 --uv-bits 7
"""
import argparse
import json
import struct
import sys
from array import array

FLOAT = 5126
UINT = 5125
USHORT = 5123


# ---------------------------------------------------------------- GLB 读写
def read_glb(path):
    with open(path, "rb") as f:
        data = f.read()
    magic, ver, total = struct.unpack("<III", data[:12])
    if magic != 0x46546C67:
        raise SystemExit("不是 glb 文件")
    off, js, bs = 12, None, None
    while off < len(data):
        clen, ctype = struct.unpack("<II", data[off:off + 8])
        body = data[off + 8:off + 8 + clen]
        if ctype == 0x4E4F534A:
            js = body
        elif ctype == 0x4E4942:
            bs = body
        off += 8 + clen
    return data, json.loads(js), bs


def pad4(n):
    return (4 - n % 4) % 4


def write_glb(path, gltf, pieces):
    """pieces: list[bytes]，与 gltf['bufferViews'] 一一对应。"""
    cursor, new_views = 0, []
    for bv, payload in zip(gltf["bufferViews"], pieces):
        nv = {"buffer": 0, "byteOffset": cursor, "byteLength": len(payload)}
        for k in ("byteStride", "target"):
            if k in bv:
                nv[k] = bv[k]
        new_views.append(nv)
        cursor += len(payload) + pad4(len(payload))
    gltf["bufferViews"] = new_views
    gltf["buffers"][0]["byteLength"] = cursor

    bin_bytes = bytearray()
    for p in pieces:
        bin_bytes += p
        bin_bytes += b"\x00" * pad4(len(p))

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * pad4(len(json_bytes))
    bin_bytes = bytes(bin_bytes)
    bin_bytes += b"\x00" * pad4(len(bin_bytes))

    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(json_bytes) + 8 + len(bin_bytes))
    out += struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    out += struct.pack("<II", len(bin_bytes), 0x4E4942) + bin_bytes
    with open(path, "wb") as f:
        f.write(out)
    return len(out)


def accessor_bytes(gltf, bs, idx):
    """读取某个 accessor 的原始字节（未用到，保留作调试用）。"""
    acc = gltf["accessors"][idx]
    bv = gltf["bufferViews"][acc["bufferView"]]
    off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    return bs[off:]


# ---------------------------------------------------------------- 核心
def cluster(positions, normals, uvs, indices, res, uv_bits):
    """按体素(+量化UV)聚类，返回 (新顶点表, 新索引)。

    UV 量化必须跟随体素分辨率：若UV 桶比体素更细，键就永远是唯一的，聚类失效。
    这里让 UV 桶数与体素数同量级（uv_res ≈ res），视觉上相当于贴图随几何一起降级。
    """
    n = len(positions) // 3
    # bbox
    xs = positions[0::3]
    ys = positions[1::3]
    zs = positions[2::3]
    lo = (min(xs), min(ys), min(zs))
    span = (max(xs) - lo[0], max(ys) - lo[1], max(zs) - lo[2])
    inv = [res / (span[i] + 1e-12) for i in range(3)]
    uv_res = uv_bits if uv_bits > 0 else res

    table = {}                      # key -> new index
    npos = array("f")
    nnor = array("f")
    nuv = array("f")
    remap = array("I", bytes(4 * n))

    for i in range(n):
        px, py, pz = positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]
        ix = int((px - lo[0]) * inv[0])
        iy = int((py - lo[1]) * inv[1])
        iz = int((pz - lo[2]) * inv[2])
        u, v = uvs[i * 2], uvs[i * 2 + 1]
        qu = uv_res - 1 if u >= 1.0 else int(u * uv_res)
        qv = uv_res - 1 if v >= 1.0 else int(v * uv_res)
        if qu < 0: qu = 0
        if qv < 0: qv = 0
        if qu >= uv_res: qu = uv_res - 1
        if qv >= uv_res: qv = uv_res - 1
        key = (ix, iy, iz, qu, qv)
        idx = table.get(key)
        if idx is None:
            idx = len(npos) // 3
            table[key] = idx
            npos.append(px); npos.append(py); npos.append(pz)
            nnor.append(normals[i * 3]); nnor.append(normals[i * 3 + 1]); nnor.append(normals[i * 3 + 2])
            nuv.append(u); nuv.append(v)
        else:
            # 同簇内取法线累加，最后统一归一化（UV 必须完全一致，故不平均）
            nnor[idx * 3] += normals[i * 3]
            nnor[idx * 3 + 1] += normals[i * 3 + 1]
            nnor[idx * 3 + 2] += normals[i * 3 + 2]
        remap[i] = idx

    # 重建索引，跳过退化三角形
    new_idx = array("I")
    for t in range(0, len(indices), 3):
        a, b, c = remap[indices[t]], remap[indices[t + 1]], remap[indices[t + 2]]
        if a == b or b == c or a == c:
            continue
        new_idx.append(a); new_idx.append(b); new_idx.append(c)

    # 法线归一化
    for i in range(len(npos) // 3):
        x, y, z = nnor[i * 3], nnor[i * 3 + 1], nnor[i * 3 + 2]
        m = (x * x + y * y + z * z) ** 0.5
        if m > 1e-9:
            nnor[i * 3] = x / m; nnor[i * 3 + 1] = y / m; nnor[i * 3 + 2] = z / m
        else:
            nnor[i * 3] = 0; nnor[i * 3 + 1] = 1; nnor[i * 3 + 2] = 0
    return npos, nnor, nuv, new_idx


def build(res, uv_bits, src):
    positions, normals, uvs, indices = src
    return cluster(positions, normals, uvs, indices, res, uv_bits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--target", type=int, default=50000, help="目标三角面数")
    ap.add_argument("--uv-bits", type=int, default=0, help="UV 量化级数（0=跟随体素分辨率，推荐默认）")
    args = ap.parse_args()

    data, gltf, bs = read_glb(args.src)
    prim = gltf["meshes"][0]["primitives"][0]
    ai = prim["attributes"]

    def load(idx, comp_size):
        acc = gltf["accessors"][idx]
        bv = gltf["bufferViews"][acc["bufferView"]]
        base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
        cnt = acc["count"]
        code = "f" if acc["componentType"] == FLOAT else "I"
        a = array(code)
        a.frombytes(bs[base:base + cnt * comp_size * a.itemsize])
        return a

    positions = load(ai["POSITION"], 3)
    normals = load(ai["NORMAL"], 3)
    uvs = load(ai["TEXCOORD_0"], 2)
    iacc = gltf["accessors"][prim["indices"]]
    ibv = gltf["bufferViews"][iacc["bufferView"]]
    ibase = ibv.get("byteOffset", 0) + iacc.get("byteOffset", 0)
    indices = array("I")
    indices.frombytes(bs[ibase:ibase + iacc["count"] * 4])

    src = (positions, normals, uvs, indices)
    src_tris = len(indices) // 3
    print("源模型: %d 顶点 / %d 三角面" % (len(positions) // 3, src_tris))

    # 二分体素分辨率。res 越大 → 体素越细 → 簇越多 → 面越多（单调递增，如
    # res=8→2.8k 面、res=32→32k 面、res=256→145k 面）。目标面数落在区间内则收敛。
    lo, hi = 4, 400
    best = None
    for _ in range(14):
        if hi - lo <= 1:
            break
        mid = (lo + hi) // 2
        npos, nnor, nuv, nidx = cluster(positions, normals, uvs, indices, mid, args.uv_bits)
        tris = len(nidx) // 3
        if tris > args.target:
            hi = mid          # 面太多 → 体素要更粗 → 减小 res
        else:
            lo = mid
            best = (npos, nnor, nuv, nidx, tris)
        if best is not None and abs(tris - args.target) / args.target < 0.05:
            break

    if best is None:
        npos, nnor, nuv, nidx = cluster(positions, normals, uvs, indices, lo, args.uv_bits)
        best = (npos, nnor, nuv, nidx, len(nidx) // 3)

    npos, nnor, nuv, nidx, tris = best
    nv_count = len(npos) // 3
    print("采用: %d 顶点 / %d 三角面 (目标 %d)" % (nv_count, tris, args.target))

    orig_views = gltf["bufferViews"]
    mn = [min(npos[0::3]), min(npos[1::3]), min(npos[2::3])]
    mx = [max(npos[0::3]), max(npos[1::3]), max(npos[2::3])]

    # 旧的几何 bufferView（POSITION/NORMAL/TEXCOORD/indices）已不再被引用，
    # 直接丢弃，只保留贴图相关的 bufferView，避免输出白白变大。
    keep_views = [gltf["images"][0]["bufferView"]]
    old_to_new = {old: new for new, old in enumerate(keep_views)}
    for im in gltf.get("images", []):
        im["bufferView"] = old_to_new[im["bufferView"]]

    gltf["accessors"] = [
        {"bufferView": len(keep_views), "componentType": FLOAT, "count": nv_count,
         "type": "VEC3", "min": mn, "max": mx},
        {"bufferView": len(keep_views) + 1, "componentType": FLOAT, "count": nv_count, "type": "VEC3"},
        {"bufferView": len(keep_views) + 2, "componentType": FLOAT, "count": nv_count, "type": "VEC2"},
        {"bufferView": len(keep_views) + 3, "componentType": UINT, "count": len(nidx), "type": "SCALAR"},
    ]
    gltf["meshes"][0]["primitives"][0] = {
        "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
        "indices": 3,
        "material": prim["material"],
    }

    new_views = [dict(orig_views[i], byteOffset=0) for i in keep_views]
    pieces = [bs[orig_views[i].get("byteOffset", 0):
                  orig_views[i].get("byteOffset", 0) + orig_views[i]["byteLength"]]
              for i in keep_views]
    for payload in (npos.tobytes(), nnor.tobytes(), nuv.tobytes(), nidx.tobytes()):
        new_views.append({"buffer": 0, "byteOffset": 0, "byteLength": len(payload)})
        pieces.append(payload)

    gltf["bufferViews"] = new_views
    size = write_glb(args.dst, gltf, pieces)
    print("写入 %s: %d bytes (原 %.1f%%)" % (args.dst, size, size / len(data) * 100))


if __name__ == "__main__":
    main()