# -*- coding: utf-8 -*-
"""GLB 体检：打印面数 / 顶点数 / 根节点变换 / 包围盒 / 贴图尺寸。

用途：验收「不超过 15000 面」这条硬指标，并确认新模型的朝向约定
      （根节点自带绕 X +90°，加载后应头朝 +Y、双脚 y=0、正面朝 +Z）
      与旧模型一致，这样 index.html 里不用再叠任何姿态旋转。

用法: python3 glb_info.py <model.glb> [更多.glb ...]
纯标准库，不需要 PIL。
"""
import json
import os
import struct
import sys

CTYPE_CODE = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
              5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
CTYPE_SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}


def quat_rot(q, x, y, z):
    qx, qy, qz, qw = q
    tx = 2.0 * (qy * z - qz * y)
    ty = 2.0 * (qz * x - qx * z)
    tz = 2.0 * (qx * y - qy * x)
    return (x + qw * tx + (qy * tz - qz * ty),
            y + qw * ty + (qz * tx - qx * tz),
            z + qw * tz + (qx * ty - qy * tx))


def inspect(path):
    data = open(path, "rb").read()
    assert struct.unpack("<I", data[:4])[0] == 0x46546C67, "不是 GLB: " + path
    off, chunks = 12, []
    while off < len(data):
        clen, ctype = struct.unpack("<II", data[off:off + 8])
        chunks.append((ctype, clen, off + 8))
        off += 8 + clen
    g = json.loads(data[chunks[0][2]:chunks[0][2] + chunks[0][1]])
    bin_off = [c[2] for c in chunks if c[0] == 0x4E4942][0]

    def acc(i):
        a = g["accessors"][i]
        bv = g["bufferViews"][a["bufferView"]]
        s = bin_off + bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        ncomp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
                 "MAT4": 16}.get(a["type"], 1)
        sz = ncomp * CTYPE_SIZE[a["componentType"]]
        import array
        arr = array.array(CTYPE_CODE[a["componentType"]][0])
        arr.frombytes(data[s:s + a["count"] * sz])
        return arr, ncomp

    tot_tri = tot_v = 0
    lo = [1e30] * 3
    hi = [-1e30] * 3
    nmesh = 0
    for mesh in g.get("meshes", []):
        for prim in mesh["primitives"]:
            nmesh += 1
            pos, nc = acc(prim["attributes"]["POSITION"])
            idx = None
            if "indices" in prim:
                idx, _ = acc(prim["indices"])
            tot_tri += (len(idx) // 3) if idx is not None else len(pos) // 3
            tot_v += len(pos) // 3
            mode = prim.get("mode", 4)
            assert mode == 4, "非三角图元 mode=%d" % mode
    # 根节点变换
    sc = g.get("scenes") or []
    q, root_name = (0.0, 0.0, 0.0, 1.0), None
    if sc and g.get("nodes"):
        root_name = sc[0]["nodes"][0]
        n = g["nodes"][root_name]
        if n.get("rotation"):
            q = tuple(n["rotation"])
        for k in range(3):
            for i in range(len(pos) // 3):
                v = quat_rot(q, pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2])
                for c in range(3):
                    lo[c] = min(lo[c], v[c])
                    hi[c] = max(hi[c], v[c])
    import math
    ang = math.degrees(2 * math.acos(max(-1.0, min(1.0, q[3]))))
    tex = []
    for im in g.get("images", []):
        bv = g["bufferViews"][im["bufferView"]]
        tex.append("%.2f MB" % (bv["byteLength"] / 1048576))

    print("=" * 68)
    print("文件      : %s  (%.2f MB)" % (os.path.basename(path),
                                          os.path.getsize(path) / 1048576))
    print("三角面数  : %d   %s" % (tot_tri, "OK ≤15000" if tot_tri <= 15000
                                   else "超限！"))
    print("顶点数    : %d    图元数: %d" % (tot_v, nmesh))
    print("根节点    : #%s  name=%s" % (root_name,
                                        (g["nodes"][root_name].get("name")
                                         if root_name is not None else "-")))
    print("根四元数  : (%.4f, %.4f, %.4f, %.4f)  旋转角 %.1f°"
          % (q[0], q[1], q[2], q[3], ang))
    if lo[0] < 1e29:
        print("变换后bbox: min=%s max=%s  尺寸=%s"
              % ([round(v, 3) for v in lo], [round(v, 3) for v in hi],
                 [round(hi[k] - lo[k], 3) for k in range(3)]))
    print("贴图      : %s" % (", ".join(tex) if tex else "无"))
    return tot_tri


if __name__ == "__main__":
    tris = [inspect(p) for p in sys.argv[1:]]
    if len(tris) == 1:
        sys.exit(0 if tris[0] <= 15000 else 1)
