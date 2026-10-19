# -*- coding: utf-8 -*-
"""离线软件光栅器：把 GLB 渲染成 6 个正交视图 PNG，用来肉眼确认模型朝向。

关键点：**必须先套用 GLB 节点自带的变换**（本模型的根节点 rotation = 绕 X +90°），
任何 glTF 加载器都会应用它；忽略它会把裸网格当成实际朝向，必然判错。

用法:
  python3 render_views.py <model.glb> <outdir> [node|corrected]
    node      只应用节点变换 = three.js 直接加载后的样子（默认）
    corrected 再叠加 index.html 里的修正（目前是绕 Z 轴 180°）
纯标准库 + PIL，无 GPU 依赖。
"""
import array
import io
import json
import os
import struct
import sys

from PIL import Image

SRC = sys.argv[1]
OUT = sys.argv[2]
MODE = sys.argv[3] if len(sys.argv) > 3 else "node"
RES = 320
FLAT = "flat" in sys.argv[4:]          # 跳过贴图，纯色渲染（用于验证几何是否正确）
os.makedirs(OUT, exist_ok=True)

data = open(SRC, "rb").read()
assert struct.unpack("<I", data[:4])[0] == 0x46546C67
off, chunks = 12, []
while off < len(data):
    clen, ctype = struct.unpack("<II", data[off:off + 8])
    chunks.append((ctype, clen, off + 8))
    off += 8 + clen
g = json.loads(data[chunks[0][2]:chunks[0][2] + chunks[0][1]])
bin_off = [c[2] for c in chunks if c[0] == 0x4E4942][0]


CTYPE_CODE = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}


def rd(i, n, code=None):
    """读 accessor。code=None 时按 componentType 自动选array 类型
    （索引可能是 uint16/uint32，硬编码 uint32 会读出越界或全 0）。"""
    a = g["accessors"][i]
    bv = g["bufferViews"][a["bufferView"]]
    s = bin_off + bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    if code is None:
        code = CTYPE_CODE[a["componentType"]]
    arr = array.array(code)
    arr.frombytes(data[s:s + a["count"] * n * arr.itemsize])
    return arr


prim = g["meshes"][0]["primitives"][0]
POS = rd(prim["attributes"]["POSITION"], 3, "f")
NRM = rd(prim["attributes"]["NORMAL"], 3, "f")
UVS = rd(prim["attributes"]["TEXCOORD_0"], 2, "f")
IND = rd(prim["indices"], 1)
NV = g["accessors"][prim["attributes"]["POSITION"]]["count"]
NTRI = len(IND) // 3


def quat_rot(q, x, y, z):
    """用四元数 (qx,qy,qz,qw) 旋转向量。"""
    qx, qy, qz, qw = q
    # t = 2 * cross(q.xyz, v)
    tx = 2.0 * (qy * z - qz * y)
    ty = 2.0 * (qz * x - qx * z)
    tz = 2.0 * (qx * y - qy * x)
    return (x + qw * tx + (qy * tz - qz * ty),
            y + qw * ty + (qz * tx - qx * tz),
            z + qw * tz + (qx * ty - qy * tx))


def node_quat():
    """取场景根节点的四元数（glTF 的 rotation 是 [x,y,z,w]）。"""
    sc = g.get("scenes") or []
    if not sc or not g.get("nodes"):
        return (0.0, 0.0, 0.0, 1.0)
    idx = sc[0]["nodes"][0]
    n = g["nodes"][idx]
    r = n.get("rotation")
    return tuple(r) if r else (0.0, 0.0, 0.0, 1.0)


def apply_quat(q, arr):
    for i in range(len(arr) // 3):
        x, y, z = quat_rot(q, arr[i * 3], arr[i * 3 + 1], arr[i * 3 + 2])
        arr[i * 3], arr[i * 3 + 1], arr[i * 3 + 2] = x, y, z


import math  # noqa: E402


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def qaxis(axis, deg):
    r = math.radians(deg) / 2
    s = math.sin(r)
    v = [0.0, 0.0, 0.0]
    v[axis] = s
    return (v[0], v[1], v[2], math.cos(r))


# 姿态：第 4 个命令行参数，可为 node / corrected / rz90 / rz-90 / rz90_node ...
#   node     = 只施加 GLB 根节点自带变换（glTF 加载器的行为）
#   <r><a>   = 额外再绕 Z 轴 ±90°（摆正用）
if MODE.startswith("rz"):
    q = qaxis(2, float(MODE[2:]))
    print("施加姿态：绕 Z 轴 %+.0f°" % float(MODE[2:]))
else:
    q = node_quat()
    print("施加姿态：GLB 根节点自带四元数 (%.4f, %.4f, %.4f, %.4f)，旋转角 %.1f°"
          % (q[0], q[1], q[2], q[3],
             math.degrees(2 * math.acos(max(-1, min(1, q[3]))))))
apply_quat(q, POS)
apply_quat(q, NRM)

im = g["images"][0]
bv = g["bufferViews"][im["bufferView"]]
tex = Image.open(io.BytesIO(
    data[bin_off + bv["byteOffset"]:bin_off + bv["byteOffset"] + bv["byteLength"]])).convert("RGB")
TW, TH = tex.size
TPX = tex.load()

lo = [min(POS[i * 3 + k] for i in range(NV)) for k in range(3)]
hi = [max(POS[i * 3 + k] for i in range(NV)) for k in range(3)]
print("变换后包围盒 min=%s max=%s" % (
    [round(v, 3) for v in lo], [round(v, 3) for v in hi]))
print("尺寸 = %s" % [round(hi[k] - lo[k], 3) for k in range(3)])

CEN = [(lo[k] + hi[k]) / 2 for k in range(3)]
SCALE = max(hi[k] - lo[k] for k in range(3))
K = RES * 0.46 / SCALE


def render(u_axis, v_axis, w_axis, cam_sign, mirror_u, name):
    """cam_sign=+1 相机在 -w 侧（最近处 = w 最小）；-1 反之。
    mirror_u=True 时屏幕右方向取 -u，相当于绕竖直轴转到背面。"""
    img = Image.new("RGB", (RES, RES), (16, 20, 30))
    px = img.load()
    zbuf = [(1e30 if cam_sign > 0 else -1e30)] * (RES * RES)
    cu, cv = CEN[u_axis], CEN[v_axis]
    sgn_u = -1.0 if mirror_u else 1.0
    hit = 0
    for t in range(NTRI):
        a, b, c = IND[t * 3], IND[t * 3 + 1], IND[t * 3 + 2]
        A, B, C = a * 3, b * 3, c * 3
        x0 = (POS[A + u_axis] - cu) * K * sgn_u + RES / 2
        y0 = RES / 2 - (POS[A + v_axis] - cv) * K
        x1 = (POS[B + u_axis] - cu) * K * sgn_u + RES / 2
        y1 = RES / 2 - (POS[B + v_axis] - cv) * K
        x2 = (POS[C + u_axis] - cu) * K * sgn_u + RES / 2
        y2 = RES / 2 - (POS[C + v_axis] - cv) * K
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if area >= -1e-9 and area <= 1e-9:
            continue
        minx = max(0, int(min(x0, x1, x2)))
        maxx = min(RES - 1, int(max(x0, x1, x2)) + 1)
        miny = max(0, int(min(y0, y1, y2)))
        maxy = min(RES - 1, int(max(y0, y1, y2)) + 1)
        if minx > maxx or miny > maxy:
            continue
        inv = 1.0 / area
        z0, z1, z2 = POS[A + w_axis], POS[B + w_axis], POS[C + w_axis]
        for py in range(miny, maxy + 1):
            fy = py + 0.5
            row = py * RES
            for pxi in range(minx, maxx + 1):
                fx = pxi + 0.5
                w0 = ((x1 - fx) * (y2 - fy) - (x2 - fx) * (y1 - fy)) * inv
                w1 = ((x2 - fx) * (y0 - fy) - (x0 - fx) * (y2 - fy)) * inv
                w2 = 1.0 - w0 - w1
                if w0 < 0 or w1 < 0 or w2 < 0:
                    continue
                k = row + pxi
                z = w0 * z0 + w1 * z1 + w2 * z2
                if cam_sign > 0:
                    if z >= zbuf[k]:
                        continue
                else:
                    if z <= zbuf[k]:
                        continue
                zbuf[k] = z
                u = w0 * UVS[a * 2] + w1 * UVS[b * 2] + w2 * UVS[c * 2]
                v = w0 * UVS[a * 2 + 1] + w1 * UVS[b * 2 + 1] + w2 * UVS[c * 2 + 1]
                if FLAT:
                    r, gg, b = 190, 200, 225
                else:
                    tx = int(u * TW)
                    ty = int(v * TH)
                    if tx < 0 or tx >= TW or ty < 0 or ty >= TH:
                        r, gg, b = 80, 80, 100
                    else:
                        r, gg, b = TPX[tx, ty]
                nw = (w0 * NRM[A + w_axis] + w1 * NRM[B + w_axis] + w2 * NRM[C + w_axis])
                lam = -cam_sign * nw
                sh = 0.45 + 0.6 * (lam if lam > 0 else 0)
                px[pxi, py] = (min(255, int(r * sh)), min(255, int(gg * sh)), min(255, int(b * sh)))
                hit += 1
    img.save(os.path.join(OUT, name))
    print("saved %-28s pixels=%d" % (name, hit))


# 屏幕上方固定为世界 +Y（站立姿态），w = 视线轴；u = 剩下的水平轴
# w=1（沿 Y 俯视）时没有"剩下的水平轴"，单独用 v=2(Z) 作屏幕上方
names = []
for w in (0, 2):
    u = [k for k in range(3) if k != w and k != 1][0]
    v = 1
    for cam_sign, tag in ((1, "front"), (-1, "back")):
        nm = "view_%s_%s.png" % ("XYZ"[w], tag)
        render(u, v, w, cam_sign, cam_sign < 0, nm)
        names.append(nm)
# 顶视图：视线沿 -Y，屏幕上方用 +Z
render(0, 2, 1, -1, False, "view_Y_top.png")
names.append("view_Y_top.png")

sheet = Image.new("RGB", (RES * 3, RES * 2), (8, 10, 14))
for i, nm in enumerate(names):
    sheet.paste(Image.open(os.path.join(OUT, nm)), ((i % 3) * RES, (i // 3) * RES))
sheet.save(os.path.join(OUT, "contact_sheet.png"))
print("saved contact_sheet.png   [X正 X背] [Z正 Z背] [顶视]")
print("正面视角 = 从角色面朝的方向看；若角色面朝 +Z 则为 view_Z_back.png")