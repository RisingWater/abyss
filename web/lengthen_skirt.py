"""裙摆下拉：把裙子本身拉长，而不是在裙子外面另加一层。

背景：上一版方案是在裙摆环下方另生成一圈锥形面，结果看起来像「在裙子外面
套了条裤子」——因为新旧几何之间有一道明显的接缝，且新面用的是独立材质。

本方案：识别裙子的顶点，把它们整体向下拉伸（裙摆落点从 y=0.17 延到接近脚踝），
腿保持原位但被裙摆包住。这样裙子和下摆是同一片连续几何、同一套贴图。

关键难点是「哪些顶点属于裙」：
- 模型是图生 3D 直出的碎片网格，下半身有 1200+ 个连通块，连通性不可用
- 贴图颜色也杂乱（裙深藏蓝、腿白长袜，但蕾丝/高光/描边都混在一起）
- 但径向直方图很干净：同一高度上裙子必然在腿的外侧（裙子是套在腿上的壳）

所以判据用「高度 + 到身体轴的半径」。脚本先打印分层统计供核对。
"""
import json
import math
import struct
import sys
from array import array
from collections import defaultdict

SRC = sys.argv[1] if len(sys.argv) > 1 else 'assets/dafeiyu_aim_15k.glb'
DST = sys.argv[2] if len(sys.argv) > 2 else 'assets/skirt/dafeiyu_long.glb'

# 目标：裙摆下缘从 y=0.17 落到 y=0.075（鞋顶在 0.060，盖过鞋口但不到脚背）
HEM_Y = 0.170         # 原裙摆下缘高度
NEW_HEM_Y = 0.075      # 目标下缘高度
HEM_R = 0.215          # 原裙摆外缘半径（用于识别）

# 裙身顶点判据：高度在 [HEM_Y, WAIST_Y]，且半径在[skirt_min_r(y), SKIRT_R_MAX]
# skirt_min_r 随高度线性收缩（裙子上宽下窄）
WAIST_Y = 0.520        # 腰线锚点：此高度不位移，再往上是上衣/围裙，不属于裙摆
SKIRT_R_MAX = 0.260    # 裙子的外缘半径上限：超过这个是头发/手臂/枪，不能跟着裙摆下拉


def load(path):
    d = open(path, 'rb').read()
    off = 12
    js = None
    bin_ = None
    bstart = 0
    while off < len(d):
        ln, ty = struct.unpack_from('<II', d, off)
        off += 8
        if ty == 0x4E4F534A:
            js = json.loads(d[off:off + ln].decode('utf-8'))
        elif ty == 0x004E4942:
            bin_ = d[off:off + ln]
            bstart = off
        off += ln
    return js, bin_, d, bstart


js, bin_, raw, bstart = load(SRC)
prim = js['meshes'][0]['primitives'][0]
CT = {5120: 'b', 5121: 'B', 5122: 'h', 5123: 'H', 5125: 'I', 5126: 'f'}


def read_acc(idx, comps):
    a = js['accessors'][idx]
    bv = js['bufferViews'][a['bufferView']]
    o = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    arr = array(CT[a['componentType']])
    arr.frombytes(bin_[o:o + a['count'] * comps * arr.itemsize])
    return arr, a['count']


pos, N = read_acc(prim['attributes']['POSITION'], 3)
nrm, _ = read_acc(prim['attributes']['NORMAL'], 3)
uv, _ = read_acc(prim['attributes']['TEXCOORD_0'], 2)
ia = js['accessors'][prim['indices']]
IND = array(CT[ia['componentType']])
_indbv = js['bufferViews'][ia['bufferView']]
IND.frombytes(bin_[_indbv.get('byteOffset', 0):_indbv.get('byteOffset', 0) + ia['count'] * IND.itemsize])
T = list(IND)

# 站立坐标：根节点绕 X +90 => y_stand = -z, z_stand = y
S = [(pos[i * 3], -pos[i * 3 + 2], pos[i * 3 + 1]) for i in range(N)]

# 身体轴心（下半身重心）
lowpts = [(x, z) for x, y, z in S if y < 0.60]
AX = (sum(p[0] for p in lowpts) / len(lowpts), sum(p[1] for p in lowpts) / len(lowpts))
H = max(p[1] for p in S) - min(p[1] for p in S)


def radius(x, z):
    return math.hypot(x - AX[0], z - AX[1])


def skirt_min_r(y):
    """该高度处裙子的内侧边界半径（用于「选裙」判据，输入是原始高度）。

    A 字裙：腰线细、下摆宽。选择区是原始高度HEM_Y..WAIST_Y，
    下摆处内边界约 0.16，腰线处收紧到 0.10。
    """
    t = (y - HEM_Y) / max(WAIST_Y - HEM_Y, 1e-6)
    t = min(max(t, 0.0), 1.0)
    return 0.160 - 0.060 * t


print('源模型 %s  顶点 %d  三角面 %d  高度 %.3f' % (SRC, N, len(T) // 3, H))
print('身体轴 (%.4f, %.4f)' % AX)
print('裙摆 %.3f -> %.3f  (下延 %.3f)' % (HEM_Y, NEW_HEM_Y, HEM_Y - NEW_HEM_Y))

# ---- 1. 选出裙子顶点 ----
skirt = []
for i, (x, y, z) in enumerate(S):
    # 选区从 HEM_Y 起：HEM_Y 以下是腿，不能跟着拉伸（否则会被拽到地面以下）
    if y < HEM_Y - 0.012 or y > WAIST_Y:
        continue
    if radius(x, z) < skirt_min_r(y) or radius(x, z) > SKIRT_R_MAX:
        continue
    skirt.append(i)

print('\n裙子顶点 %d / %d (%.1f%%)' % (len(skirt), N, len(skirt) / N * 100))

# 分层核对
by_h = defaultdict(int)
for i in skirt:
    by_h[round(S[i][1], 2)] += 1
print('\n分层分布（确认裙身连续、无空洞）：')
for k in sorted(by_h):
    print('  y=%.2f  %4d  %s' % (k, by_h[k], '#' * min(by_h[k] // 5, 40)))

ys = [S[i][1] for i in skirt]
rs = [radius(S[i][0], S[i][2]) for i in skirt]
print('\n裙区y 范围 [%.3f, %.3f]   r 范围 [%.3f, %.3f]'
      % (min(ys), max(ys), min(rs), max(rs)))

if len(skirt) < 100:
    print('\n裙子顶点太少，判据可能不对，中止。')
    sys.exit(1)

# ---- 2. 垂直拉伸：腰线为锚点，下摆向下延到 NEW_HEM_Y ----
# 保持腰线（WAIST_Y）不动，把下摆从 HEM_Y 线性压到 NEW_HEM_Y：
#   y_new = WAIST_Y - (WAIST_Y - NEW_HEM_Y) * (WAIST_Y - y) / (WAIST_Y - HEM_Y)
# y = WAIST_Y 时 y_new = WAIST_Y（不动）；y = HEM_Y 时 y_new = NEW_HEM_Y（下摆落点）。
SPAN = WAIST_Y - HEM_Y
for i in skirt:
    x, y, z = S[i]
    y_new = WAIST_Y - (WAIST_Y - NEW_HEM_Y) * (WAIST_Y - y) / SPAN
    pos[i * 3] = x       # x_stand = x_orig
    pos[i * 3 + 2] = -y_new   # y_stand = -z_orig  ->  z_orig = -y_stand
    # z_stand = y_orig 保持不变，故pos[i*3+1] 不动

print('\n垂直拉伸完成。裙摆下缘 %.3f -> %.3f' % (HEM_Y, NEW_HEM_Y))

# ---- 3. 腿：往内收，压进裙摆内（只改水平方向，高度不变）----
# 坐标映射：站立 (x, y, z) = (x_orig, -z_orig, y_orig)
# 反解：x_orig = x, y_orig = z, z_orig = -y
# 所以改「站立 z」时必须写 pos[i*3+1]，改「站立 y」时写 pos[i*3+2]。
# 这里只改水平半径 -> 同时动 x_orig 和 y_orig，但**不能碰 z_orig**（否则高度被改）。
shrink = 0
for i, (x, y, z) in enumerate(S):
    if y >= NEW_HEM_Y:
        continue          # 裙摆以下才需要藏
    r = radius(x, z)
    if r <= 1e-6:
        continue
    # 越靠下收得越多：k=1 在 y=0，k=0 在 y=NEW_HEM_Y
    k = 1.0 - y / max(NEW_HEM_Y, 1e-6)
    target = 0.086# 收到裙摆内壁
    r_new = r + (target - r) * (0.85 * k)
    # 只动 x_orig 和 y_orig（水平面内），z_orig 保持不变 => 高度不变
    pos[i * 3] = AX[0] + (x - AX[0]) / r * r_new
    pos[i * 3 + 1] = AX[1] + (z - AX[1]) / r * r_new
    shrink += 1
print('腿部内收 %d 个顶点' % shrink)

# ---- 4. 重建法线（裙摆拉伸后旧法线失效）----
# 站立 (nx, ny, nz) -> 原始 (nx, nz, -ny)，因为 y_stand=-z_orig 且 z_stand=y_orig
skirt_set = set(skirt)
for i in skirt:
    x, y, z = S[i]
    r = radius(x, z)
    # 锥面法线：水平朝外 + 一点竖直分量，越靠下摆越平（外张）
    # t 基于原始高度：0=腰线, 1=下摆
    t = min(max((y - HEM_Y) / max(WAIST_Y - HEM_Y, 1e-6), 0.0), 1.0)
    nx = (x - AX[0]) / max(r, 1e-6)
    nz = (z - AX[1]) / max(r, 1e-6)
    ny = 0.45 * (1.0 - t)
    ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    nrm[i * 3] = nx / ln
    nrm[i * 3 + 1] = nz / ln
    nrm[i * 3 + 2] = -ny / ln

# 非裙区顶点：裙摆以下的一律朝下（反正被裙摆遮住，看不见）
for i in range(N):
    if i in skirt_set:
        continue
    if S[i][1] < HEM_Y:
        nrm[i * 3] = 0.0
        nrm[i * 3 + 1] = 0.0
        nrm[i * 3 + 2] = -1.0

# ---- 5. 写回 GLB（保留原有 bufferViews，图片索引不能失效）----
old_views = js['bufferViews']
base_view = len(old_views)


def pad4(b):
    return b + b'\0' * ((4 - len(b) % 4) % 4)


parts = [pad4(bin_)]
views = list(old_views)
cur = len(pad4(bin_))


def emit(arr, ctype, tgt, comps):
    global cur
    b = pad4(array(ctype, arr).tobytes())
    views.append({'buffer': 0, 'byteOffset': cur, 'byteLength': len(b), 'target': tgt})
    parts.append(b)
    cur += len(b)


emit(list(pos), 'f', 34962, 3)
emit(list(nrm), 'f', 34962, 3)
emit(list(uv), 'f', 34962, 2)
emit(T, CT[ia['componentType']], 34963, 1)

js['buffers'] = [{'byteLength': cur}]
js['bufferViews'] = views
js['accessors'] = [
    {'bufferView': base_view, 'componentType': 5126, 'count': N, 'type': 'VEC3'},
    {'bufferView': base_view + 1, 'componentType': 5126, 'count': N, 'type': 'VEC3'},
    {'bufferView': base_view + 2, 'componentType': 5126, 'count': N, 'type': 'VEC2'},
    {'bufferView': base_view + 3, 'componentType': ia['componentType'],
     'count': len(T), 'type': 'SCALAR'},
]
js['meshes'][0]['primitives'][0]['attributes'] = {'POSITION': 0, 'NORMAL': 1, 'TEXCOORD_0': 2}
js['meshes'][0]['primitives'][0]['indices'] = 3


def save(path, js_, data):
    jsb = json.dumps(js_, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    jsb += b' ' * ((4 - len(jsb) % 4) % 4)
    total = 12 + 8 + len(jsb) + 8 + len(data)
    out = bytearray()
    out += b'glTF' + struct.pack('<II', 2, total)
    out += struct.pack('<II', len(jsb), 0x4E4F534A) + jsb
    out += struct.pack('<II', len(data), 0x004E4942) + data
    open(path, 'wb').write(out)


save(DST, js, b''.join(parts))
print('\n输出: %s  (%.1f KB)' % (DST, len(b''.join(parts)) / 1024))
print('三角面 %d  顶点 %d  （与原模型一致，纯顶点位移）' % (len(T) // 3, N))