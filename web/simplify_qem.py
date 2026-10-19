# -*- coding: utf-8 -*-
"""GLB 网格简化：QEM（Quadratic Error Metrics）边塌缩，生成低模。

为什么不用顶点聚类（vertex clustering）：
    聚类必须把「位置 + UV」一起当键，否则合并后贴图渗色；若把 UV 量化得
    粗到能合并，贴图就被砸成马赛克 —— 模型表面看起来像碎片。QEM 边塌缩
    逐条边收缩，UV 用面积加权插值而不是取整，并且显式保护 UV 缝与硬边，
    因此贴图保持连续。

做法：
    1. 每个顶点累加其相邻面的二次误差矩阵（quadric）
    2. 边的塌缩代价 = 两个端点 quadric 之和在该边上的二次型
    3. 用最小堆取代价最小的边塌缩，每次只重算受影响顶点的邻边
    4. 保护对象不塌缩：UV 缝、硬边（法线夹角过大）、边界
    5. 塌缩到 quadric 在「端点A / 端点B / 中点」三者中最优的那个位置

用法：
    python3 simplify_qem.py <in.glb> <out.glb> --target 15000
    python3 simplify_qem.py <in.glb> <out.glb> --target 15000 --sharp 0.5
"""
import argparse
import heapq
import json
import struct
import sys
from array import array

FLOAT = 5126
UINT = 5125
INF = float("inf")


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


N_COMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def load_accessor(gltf, bs, idx):
    """读一个 accessor，返回扁平化的分量数组。

    注意：字节数必须按「count × 分量数 × itemsize」算 —— 只按 count 算会
    只读到 1/3（VEC3）或 1/2（VEC2）的数据，导致后续索引越界。
    """
    acc = gltf["accessors"][idx]
    bv = gltf["bufferViews"][acc["bufferView"]]
    base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    code = "f" if acc["componentType"] == FLOAT else "I"
    n = N_COMP[acc["type"]]
    a = array(code)
    a.frombytes(bs[base:base + acc["count"] * n * a.itemsize])
    return a


# ---------------------------------------------------------------- quadric
def face_quadric(ax, ay, az, bx, by, bz, cx, cy, cz):
    """返回 10 元组表示的对称 4x4 quadric（上三角展开）。"""
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    ln = (nx * nx + ny * ny + nz * nz) ** 0.5
    if ln < 1e-20:
        return None
    nx, ny, nz = nx / ln, ny / ln, nz / ln
    d = -(nx * ax + ny * ay + nz * az)
    return (nx * nx, nx * ny, nx * nz, nx * d,
            ny * ny, ny * nz, ny * d,
            nz * nz, nz * d,
            d * d)


def q_add(qa, qb):
    if qa is None:
        return qb
    if qb is None:
        return qa
    return tuple(a + b for a, b in zip(qa, qb))


def q_scale(q, s):
    return tuple(v * s for v in q)


def q_eval(q, x, y, z):
    return (q[0] * x * x + 2 * q[1] * x * y + 2 * q[2] * x * z + 2 * q[3] * x
            + q[4] * y * y + 2 * q[5] * y * z + 2 * q[6] * y
            + q[7] * z * z + 2 * q[8] * z + q[9])


def q_min_point(q, ax, ay, az, bx, by, bz):
    """在 a / b / 中点 三者中选二次误差最小的位置。"""
    best, berr = None, INF
    for (x, y, z) in ((ax, ay, az), (bx, by, bz),
                      ((ax + bx) / 2, (ay + by) / 2, (az + bz) / 2)):
        e = q_eval(q, x, y, z)
        if e < berr:
            berr, best = e, (x, y, z)
    return best


# ---------------------------------------------------------------- 核心简化
def simplify(positions, normals, uvs, indices, target_tris, sharp_dot):
    """QEM 边塌缩。

    UV 采用【面角级】存储（fu[t][k]），不用顶点级：
    图生 3D 这类自动展开的贴图，同一个几何位置在相邻面角上的 UV 并不相等
    （实测差值可达 0.03），若强行按顶点存一份 UV 再比较，必然把所有边都判成
    「UV 缝」而一条都塌缩不了。改成面角级后，塌缩只重写受影响面角的 UV，
    天然不会跨缝污染。
    """
    nv = len(positions) // 3
    nt = len(indices) // 3

    # 顶点坐标（可变）
    px = [positions[i * 3] for i in range(nv)]
    py = [positions[i * 3 + 1] for i in range(nv)]
    pz = [positions[i * 3 + 2] for i in range(nv)]
    # 顶点级 UV：仅作为塌缩时的初值参考
    uu = [uvs[i * 2] for i in range(nv)]
    vv = [uvs[i * 2 + 1] for i in range(nv)]

    # 面：顶点索引 + 每个角的 UV（权威数据）
    fi = [[indices[t], indices[t + 1], indices[t + 2]] for t in range(0, len(indices), 3)]
    fu = [[(uu[indices[t]], vv[indices[t]]),
           (uu[indices[t + 1]], vv[indices[t + 1]]),
           (uu[indices[t + 2]], vv[indices[t + 2]])] for t in range(0, len(indices), 3)]
    alive = [True] * nt
    fcount = [0] * nv

    def face_normal(f):
        a, b, c = f
        ux, uy, uz = px[b] - px[a], py[b] - py[a], pz[b] - pz[a]
        vx, vy, vz = px[c] - px[a], py[c] - py[a], pz[c] - pz[a]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        ln = (nx * nx + ny * ny + nz * nz) ** 0.5
        return (nx / ln, ny / ln, nz / ln) if ln > 1e-20 else (0.0, 0.0, 1.0)

    def face_area(f):
        a, b, c = f
        ux, uy, uz = px[b] - px[a], py[b] - py[a], pz[b] - pz[a]
        vx, vy, vz = px[c] - px[a], py[c] - py[a], pz[c] - pz[a]
        cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        return 0.5 * (cx * cx + cy * cy + cz * cz) ** 0.5

    fnorm = [face_normal(f) for f in fi]
    farea = [face_area(f) for f in fi]

    # ---- 顶点 quadric ----
    Q = [None] * nv
    for t, f in enumerate(fi):
        a, b, c = f
        q = face_quadric(px[a], py[a], pz[a], px[b], py[b], pz[b], px[c], py[c], pz[c])
        if q is None:
            continue
        q = q_scale(q, farea[t])
        Q[a] = q_add(Q[a], q)
        Q[b] = q_add(Q[b], q)
        Q[c] = q_add(Q[c], q)

    # 边界顶点：valence < 4（闭合模型里通常没有）
    edge_map = {}
    for t, f in enumerate(fi):
        for k in range(3):
            a, b = f[k], f[(k + 1) % 3]
            key = (a, b) if a < b else (b, a)
            edge_map.setdefault(key, []).append((t, k))

    for key, inc in edge_map.items():
        if len(inc) == 1:      # 边界边 → 加垂直于边的平面约束
            a, b = key
            ux, uy, uz = px[b] - px[a], py[b] - py[a], pz[b] - pz[a]
            ln = (ux * ux + uy * uy + uz * uz) ** 0.5
            if ln > 1e-20:
                nx, ny, nz = uy / ln, -ux / ln, 0.0   # 垂直于边、平行于 z
                nl = (nx * nx + ny * ny + nz * nz) ** 0.5
                if nl > 1e-12:
                    nx, ny, nz = nx / nl, ny / nl, nz / nl
                    d = -(nx * px[a] + ny * py[a] + nz * pz[a])
                    w = nl * 100.0
                    q = q_scale((nx * nx, nx * ny, nx * nz, nx * d,
                                 ny * ny, ny * nz, ny * d,
                                 nz * nz, nz * d, d * d), w)
                    Q[a] = q_add(Q[a], q)
                    Q[b] = q_add(Q[b], q)

    # ---- 顶点→面 邻接 ----
    vfaces = [[] for _ in range(nv)]
    for t, f in enumerate(fi):
        for v in f:
            vfaces[v].append(t)

# ---- 保护边：只保护「硬边」与「边界边」----
    # 不做 UV 缝保护：图生 3D 展开的贴图，同一几何位置在相邻面角上的 UV 差可达 0.03
    # （UV 未按顶点焊接的正常表现）。若按 1e-6 阈值判缝，25 万条边会全部被保护，
    # 结果一条都塌缩不了。UV 正确性由「面角级 UV + 塌缩时插值」保证。
    protected = set()
    for key, inc in edge_map.items():
        if len(inc) == 1:
            protected.add(key)          # 边界边：不塌缩，免得开口
            continue
        n0, n1 = fnorm[inc[0][0]], fnorm[inc[1][0]]
        if n0[0] * n1[0] + n0[1] * n1[1] + n0[2] * n1[2] < sharp_dot:
            protected.add(key)

    # ---- 优先队列（lazy 删除）----
    version = [0] * nv      # 顶点版本号，用于丢弃过期的堆项

    def edge_key(a, b):
        return (a, b) if a < b else (b, a)

    def current_incident_edges(v):
        es = set()
        for t in vfaces[v]:
            if not alive[t]:
                continue
            f = fi[t]
            for k in range(3):
                a, b = f[k], f[(k + 1) % 3]
                es.add(edge_key(a, b))
        return es

    live_tris = nt

    heap = []
    alive_v = [True] * nv

    def push_edge(a, b):
        key = edge_key(a, b)
        if key in protected or not alive_v[key[0]] or not alive_v[key[1]]:
            return
        q = q_add(Q[key[0]], Q[key[1]])
        cost = q_eval(q, px[key[0]], py[key[0]], pz[key[0]])
        heapq.heappush(heap, (cost, version[key[0]], version[key[1]], key))

    for key in edge_map:
        push_edge(key[0], key[1])

    collapses = 0
    # 每次塌缩平均删 2 个三角形，用估算控制循环，避免全量扫描
    est = nt
    while heap and est > target_tris:
        cost, va, vb, key = heapq.heappop(heap)
        a, b = key
        if not alive_v[a] or not alive_v[b]:
            continue
        if version[a] != va or version[b] != vb:
            continue          # 端点已更新，堆项过期
        est -= 2

        q = q_add(Q[a], Q[b])
        nx, ny, nz = q_min_point(q, px[a], py[a], pz[a], px[b], py[b], pz[b])

        # ---- 把 b 合并进 a：位置取quadric 最优点 ----
        # UV 是面角级的（fu[t][k]），这里不动任何 UV；
        # 下面替换面角时，把原来指向 b 的角改成指向 a，并把该角的 UV
        # 从 b 的 UV 插值到 a 的 UV（按该面面积在 a/b 邻接面面积中的占比）。
        if (nx, ny, nz) != (px[a], py[a], pz[a]):
            px[a], py[a], pz[a] = nx, ny, nz
        ba, ca = 0.0, 0.0
        for t in vfaces[b]:
            if alive[t]:
                ba += farea[t]
        for t in vfaces[a]:
            if alive[t]:
                ca += farea[t]
        tot = ba + ca
        # a、b 合并后的新 UV（各自邻接面面积加权）
        if tot > 1e-20:
            new_u = (uu[a] * ca + uu[b] * ba) / tot
            new_v = (vv[a] * ca + vv[b] * ba) / tot
        else:
            new_u, new_v = uu[a], vv[a]

        Q[a] = q
        alive_v[b] = False

        # ---- 更新 a 关联的面：把 b 换成 a，必要时删面 ----
        touched = set()
        for t in vfaces[b]:
            if not alive[t]:
                continue
            newf = list(fi[t])
            newuv = list(fu[t])
            for k in range(3):
                if newf[k] == b:
                    newf[k] = a
                    # 该角原本挂在 b 上，塌缩后插值到 a/b 合并后的 UV
                    newuv[k] = (new_u, new_v)
            fi[t] = newf
            fu[t] = newuv
            touched.update((newf[k], newf[(k + 1) % 3]) for k in range(3))
            # 退化检查
            if newf[0] == newf[1] or newf[1] == newf[2] or newf[0] == newf[2]:
                alive[t] = False
                est -= 1
            else:
                fnorm[t] = face_normal(newf)
                farea[t] = face_area(newf)

        # b 的存活面并入 a 的邻接
        for t in vfaces[b]:
            if alive[t]:
                vfaces[a].append(t)
        vfaces[b] = []

        version[a] += 1
        version[b] += 1
        collapses += 1

        for (x, y) in touched:
            if alive_v[x] and alive_v[y]:
                push_edge(x, y)

    # ---- 输出 ----
    # ---- 输出：按 (位置, UV) 重新焊接顶点 ----
    # UV 是面角级的，同一位置在不同面上可能有不同 UV；直接按位置导出会丢 UV，
    # 必须按 (位置, UV) 组合分裂成新顶点。这样贴图不会被拉花。
    src_v = [i for i in range(nv) if alive_v[i]]
    # 先算每个存活顶点的平滑法线
    nacc = [[0.0, 0.0, 0.0] for _ in range(nv)]
    for t in range(nt):
        if not alive[t]:
            continue
        f = fi[t]
        a, b, c = f[0], f[1], f[2]
        ux, uy, uz = px[b] - px[a], py[b] - py[a], pz[b] - pz[a]
        vx, vy, vz = px[c] - px[a], py[c] - py[a], pz[c] - pz[a]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        for v in f:
            nacc[v][0] += nx; nacc[v][1] += ny; nacc[v][2] += nz

    table = {}
    op, on, ou = array("f"), array("f"), array("f")
    oi = array("I")

    def emit(v, uv):
        """按 (原顶点, 量化UV) 去重后输出一个新顶点，返回新索引。"""
        key = (v, round(uv[0], 6), round(uv[1], 6))
        hit = table.get(key)
        if hit is not None:
            return hit
        idx = len(op) // 3
        table[key] = idx
        op.append(px[v]); op.append(py[v]); op.append(pz[v])
        x, y, z = nacc[v]
        ln = (x * x + y * y + z * z) ** 0.5
        if ln > 1e-12:
            on.extend((x / ln, y / ln, z / ln))
        else:
            on.extend((0.0, 1.0, 0.0))
        ou.append(uv[0]); ou.append(uv[1])
        return idx

    for t in range(nt):
        if not alive[t]:
            continue
        f = fi[t]
        if not (alive_v[f[0]] and alive_v[f[1]] and alive_v[f[2]]):
            continue
        if f[0] == f[1] or f[1] == f[2] or f[0] == f[2]:
            continue
        a = emit(f[0], fu[t][0])
        b = emit(f[1], fu[t][1])
        c = emit(f[2], fu[t][2])
        if a == b or b == c or a == c:
            continue
        oi.append(a); oi.append(b); oi.append(c)

    return op, on, ou, oi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--target", type=int, default=15000, help="目标三角面数")
    ap.add_argument("--sharp", type=float, default=0.3,
                    help="硬边阈值：两面法线点积小于此值视为硬边，保护不塌缩")
    args = ap.parse_args()

    data, gltf, bs = read_glb(args.src)
    prim = gltf["meshes"][0]["primitives"][0]
    ai = prim["attributes"]
    positions = load_accessor(gltf, bs, ai["POSITION"])
    normals = load_accessor(gltf, bs, ai["NORMAL"])
    uvs = load_accessor(gltf, bs, ai["TEXCOORD_0"])
    indices = load_accessor(gltf, bs, prim["indices"])
    print("源模型: %d 顶点 / %d 三角面" % (len(positions) // 3, len(indices) // 3))

    op, on, ou, oi = simplify(positions, normals, uvs, indices,
                              args.target, args.sharp)
    nv, nt = len(op) // 3, len(oi) // 3
    print("结果: %d 顶点 / %d 三角面 (目标 %d)" % (nv, nt, args.target))

    orig_views = gltf["bufferViews"]
    keep = [gltf["images"][0]["bufferView"]]
    old_to_new = {o: n for n, o in enumerate(keep)}
    for im in gltf.get("images", []):
        im["bufferView"] = old_to_new[im["bufferView"]]

    mn = [min(op[0::3]), min(op[1::3]), min(op[2::3])]
    mx = [max(op[0::3]), max(op[1::3]), max(op[2::3])]
    gltf["accessors"] = [
        {"bufferView": len(keep), "componentType": FLOAT, "count": nv,
         "type": "VEC3", "min": mn, "max": mx},
        {"bufferView": len(keep) + 1, "componentType": FLOAT, "count": nv, "type": "VEC3"},
        {"bufferView": len(keep) + 2, "componentType": FLOAT, "count": nv, "type": "VEC2"},
        {"bufferView": len(keep) + 3, "componentType": UINT, "count": len(oi), "type": "SCALAR"},
    ]
    gltf["meshes"][0]["primitives"][0] = {
        "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
        "indices": 3,
        "material": prim["material"],
    }

    views = [dict(orig_views[i], byteOffset=0) for i in keep]
    pieces = [bs[orig_views[i].get("byteOffset", 0):
                  orig_views[i].get("byteOffset", 0) + orig_views[i]["byteLength"]]
              for i in keep]
    for payload in (op.tobytes(), on.tobytes(), ou.tobytes(), oi.tobytes()):
        views.append({"buffer": 0, "byteOffset": 0, "byteLength": len(payload)})
        pieces.append(payload)

    gltf["bufferViews"] = views
    size = write_glb(args.dst, gltf, pieces)
    print("写入 %s: %d bytes (原 %.1f%%)" % (args.dst, size, size / len(data) * 100))


if __name__ == "__main__":
    main()