# -*- coding: utf-8 -*-
"""离线渲染：正面/侧面视图 + 站立高度标尺，按高度区间上色。

用途：肉眼确认「裙子到底在哪一段高度」，好给顶点着色器的摆动权重定阈值。
之前仅凭半径直方图猜裙区，把头发/上衣/手臂也卷进了摆动范围，必须看图。

上色规则（与 index.html 的 SKIRT_WAIST/SKIRT_HEM 对齐）：
  暖色= 裙区 [0.075, 0.520]
  绿色= 腿鞋 < 0.075（权重必须为 0，否则鞋子会跟着平移）
  冷色= 腰以上 > 0.520（必须完全不动）

用法: python3 skirt_zones.py <model.glb>
输出: skirt_zones_front.png / skirt_zones_side.png
"""
import json
import struct
import sys
from array import array
from math import hypot

from PIL import Image, ImageDraw

SRC = sys.argv[1] if len(sys.argv) > 1 else 'assets/dafeiyu_long_skirt.glb'
# 腰线/下摆阈值。实测：裙面半径中位数稳定在 0.17，而 0.30~0.52 那段半径中位数 0.26
# ——那是垂到腰下的头发，不是裙子。所以腰线取 0.30（≈身高的 29%，与写实人体比例吻合），
# 而不是 lengthen_skirt.py 里当初用的 0.52。
WAIST = float(sys.argv[2]) if len(sys.argv) > 2 else 0.30
HEM = 0.075
# 半径门限：裙面是套在腿外的壳，超过这个半径的是头发/手臂/枪
R_MAX = float(sys.argv[3]) if len(sys.argv) > 3 else 0.215

# ---- GLB 解析 ----
data = open(SRC, 'rb').read()
off, js, bin_ = 12, None, None
while off < len(data):
    ln, ty = struct.unpack_from('<II', data, off)
    off += 8
    if ty == 0x4E4F534A:
        js = json.loads(data[off:off + ln].decode('utf-8'))
    elif ty == 0x004E4942:
        bin_ = data[off:off + ln]
    off += ln

prim = js['meshes'][0]['primitives'][0]
# componentType -> (array typecode, 每分量字节数)
CT = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2),
      5123: ('H', 2), 5125: ('I', 4), 5126: ('f', 4)}
NCOMP = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}


def read_acc(i):
    a = js['accessors'][i]
    bv = js['bufferViews'][a['bufferView']]
    start = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    code, size = CT[a['componentType']]
    # 注意：a['count'] 是「元素个数」，字节数还要乘以每元素的分量数（VEC3 = 3），
    # 漏乘会读到的数组只有应有长度的 1/3，后面索引直接越界
    arr = array(code)
    arr.frombytes(bin_[start:start + a['count'] * NCOMP[a['type']] * size])
    return arr, a['count']


P, NV = read_acc(prim['attributes']['POSITION'])
IDX, NI = read_acc(prim['indices'])

# GLB 根节点自带 rotation =绕 X +90°，站立坐标 stand = (x, -z, y)
V = [(P[i * 3], -P[i * 3 + 2], P[i * 3 + 1]) for i in range(NV)]
TRI = list(IDX)[:NI // 3 * 3]
H = max(v[1] for v in V)

# 身体轴：下半身顶点的平均 (x, z)。径向门限要绕它算，所以必须在渲染前求好。
AX = AZ = 0.0
cnt = 0
for x, y, z in V:
    if y < 0.60:
        AX += x
        AZ += z
        cnt += 1
AX /= cnt
AZ /= cnt

print('顶点 %d  三角面 %d  身高 %.3f  身体轴 (%.4f, %.4f)'
      % (NV, len(TRI) // 3, H, AX, AZ))
print('裙区判据：HEM<= y <= %.3f  且 r <= %.3f\n' % (WAIST, R_MAX))

RES_W, VIEW_W = 300, 0.78
SC = RES_W / VIEW_W


def render(path, xaxis, zaxis):
    """xaxis/zaxis: 用哪两个轴当画面横/纵（正视= x/y，侧视= z/y）"""
    img = Image.new('RGB', (RES_W, int((H + 0.12) * SC)), (20, 24, 36))
    dr = ImageDraw.Draw(img)

    def px(v):
        return (RES_W / 2 + v[xaxis] * SC, 0.06 + (H - 0.06 - v[1]) * SC)

    for k in range(0, 24):
        yy = k * 0.05
        if yy > H + 0.01:
            break
        Y = px((0, yy, 0))[1]
        dr.line([(0, Y), (RES_W, Y)], fill=(58, 84, 64))
        dr.text((3, Y - 11), '%.2f' % yy, fill=(110, 225, 140))
    for lab, yy, col in (('WAIST', WAIST, (255, 120, 90)), ('HEM', HEM, (90, 160, 255))):
        Y = px((0, yy, 0))[1]
        dr.line([(0, Y), (RES_W, Y)], fill=col)
        dr.text((RES_W - 46, Y - 11), lab, fill=col)

    for t in range(0, len(TRI), 3):
        a, b, c = V[TRI[t]], V[TRI[t + 1]], V[TRI[t + 2]]
        my = (a[1] + b[1] + c[1]) / 3
        r = (hypot(a[0] - AX, a[2] - AZ) + hypot(b[0] - AX, b[2] - AZ) + hypot(c[0] - AX, c[2] - AZ)) / 3
        if my < HEM:
            col = (90, 200, 120)        # 腿鞋
        elif my <= WAIST and r <= R_MAX:
            col = (235, 170, 90)       # 裙区
        else:
            col = (120, 140, 185)      # 腰以上 / 半径超限（头发、手臂、枪）
        dr.polygon([px(a), px(b), px(c)], fill=col)
    img.save(path)
    print('  ->', path)


render('skirt_zones_front.png', 0, 2)
render('skirt_zones_side.png', 2, 0)