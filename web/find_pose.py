# -*- coding: utf-8 -*-
"""枚举候选姿态，找出「新模型」的正确站立朝向。

GLTFLoader 会把 GLB 根节点的 rotation 应用到 scene 的**直接子节点**上，
gltf.scene 自身的 quaternion 保持单位 —— 所以不能靠看 scene.quaternion 判断。

做法：读本地坐标的 POSITION，枚举若干候选四元数，选出
  (1) 变换后世界 Y 方向最长（站立而非躺倒）
  (2) 变换后「头顶方向」朝向 +Z（正面朝相机默认方向）
的那一个。
"""
import json
import math
import struct
import sys
from array import array

GLB = sys.argv[1] if len(sys.argv) > 1 else "assets/dafeiyu_15k.glb"

data = open(GLB, "rb").read()
off, g = 12, None
while off < len(data):
    clen, ctype = struct.unpack("<II", data[off:off + 8])
    if ctype == 0x4E4F534A:
        g = json.loads(data[off + 8:off + 8 + clen])
    elif ctype == 0x4E4942:
        bin_off = off + 8
    off += 8 + clen

CT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}


def rd(i, n):
    a = g["accessors"][i]
    bv = g["bufferViews"][a["bufferView"]]
    s = bin_off + bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    arr = array(CT[a["componentType"]])
    arr.frombytes(data[s:s + a["count"] * n * arr.itemsize])
    return arr


prim = g["meshes"][0]["primitives"][0]
POS = rd(prim["attributes"]["POSITION"], 3)
NV = g["accessors"][prim["attributes"]["POSITION"]]["count"]
print("本地包围盒 min=%s max=%s" % (
    [round(min(POS[i * 3 + k] for i in range(NV)), 3) for k in range(3)],
    [round(max(POS[i * 3 + k] for i in range(NV)), 3) for k in range(3)]))


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


def qrot(q, x, y, z):
    qx, qy, qz, qw = q
    tx = 2.0 * (qy * z - qz * y)
    ty = 2.0 * (qz * x - qx * z)
    tz = 2.0 * (qx * y - qy * x)
    return (x + qw * tx + (qy * tz - qz * ty),
            y + qw * ty + (qz * tx - qx * tz),
            z + qw * tz + (qx * ty - qy * tx))


def evaluate(q, label):
    lo = [1e9] * 3
    hi = [-1e9] * 3
    # 「头顶」= 本地 +X 端（长轴）。候选旋转里最长轴是 X，所以先看哪个轴被转到 +Y
    for i in range(NV):
        x, y, z = qrot(q, POS[i * 3], POS[i * 3 + 1], POS[i * 3 + 2])
        for k, val in enumerate((x, y, z)):
            if val < lo[k]:
                lo[k] = val
            if val > hi[k]:
                hi[k] = val
    size = [hi[k] - lo[k] for k in range(3)]
    # 本地 +X 端在世界里的方向 = 正面/头顶判定依据
    hx, hy, hz = qrot(q, 1.0, 0.0, 0.0)
    upright = size[1] > size[0] and size[1] > size[2]
    print("%-34s 尺寸=%s  %s  +X端→(%+.2f,%+.2f,%+.2f)" % (
        label, [round(v, 3) for v in size],
        "站立" if upright else "不 upright", hx, hy, hz))
    return size, upright, (hx, hy, hz)


CANDS = [
    ("不动", (0, 0, 0, 1)),
    ("Rx+90（GLB 根节点自带）", qaxis(0, 90)),
    ("Rz+90", qaxis(2, 90)),
    ("Rz-90", qaxis(2, -90)),
    ("Ry+90", qaxis(1, 90)),
    ("Ry-90", qaxis(1, -90)),
    ("Rx+90∘Rz+90", qmul(qaxis(0, 90), qaxis(2, 90))),
    ("Rx+90∘Rz-90", qmul(qaxis(0, 90), qaxis(2, -90))),
    ("Rz+90∘Rx+90", qmul(qaxis(2, 90), qaxis(0, 90))),
    ("Rz-90∘Rx+90", qmul(qaxis(2, -90), qaxis(0, 90))),
    ("Ry+90∘Rx+90", qmul(qaxis(1, 90), qaxis(0, 90))),
    ("Ry-90∘Rx+90", qmul(qaxis(1, -90), qaxis(0, 90))),
]

print("")
good = []
for label, q in CANDS:
    size, upright, hx = evaluate(q, label)
    if upright:
        good.append((label, q, hx))

print("\nupright 的候选中，+X端朝 +Z 的（即正面朝 +Z）：")
found = False
for label, q, hx in good:
    if hx[2] > 0.9:
        print("  -> %s   [%.4f, %.4f, %.4f, %.4f]" % (label, q[0], q[1], q[2], q[3]))
        found = True
if not found:
    print("  （无 —— +X 端不是头顶方向，需另判）")
    for label, q, hx in good:
        print("  upright: %-24s +X端→%s" % (label, [round(v, 2) for v in hx]))
