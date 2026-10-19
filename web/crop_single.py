# -*- coding: utf-8 -*-
"""从原始立绘里裁出「单个角色」面板，供图生 3D 使用。

为什么必须裁成单栏：
    实测（2026-10-19）把三视图拼成一张整图提交，服务端会把每一栏当成
    独立主体各生成一个角色 —— 结果是 2~3 个角色并排出现在同一个网格里，
    而不是融合成一个 3D 角色。旧版 dafeiyu_15k.glb 就是这么来的（三只），
    所以三视图拼接这条路是死的。要单角色模型，只能喂单栏图。

用法:
    python3 crop_single.py <src.png> <out.png> <panel_index> [thresh]

    panel_index 从 0 开始，按「有内容的列区间」从左到右编号。
    自动裁掉白边、统一留 12px 白边。

纯 PIL（系统 python3 才有 PIL）。不读写 web/assets/ref/ 下的任何文件。
"""
import os
import sys

from PIL import Image

BLANK = int(sys.argv[4]) if len(sys.argv) > 4 else 245
PAD = 12


def content_mask(img, thresh):
    """二值掩膜：内容=255，背景=0。"""
    return img.convert('L').point(lambda v: 255 if v < thresh else 0, mode='L')


def column_runs(img, thresh, min_w=20, vshrink=8):
    """按空白列把图切成若干栏，返回每栏的 (x0, x1)。

    先把掩膜 BOX 缩到 1/vshrink 高度再统计，纯 Python 循环量降到 ~1/8。
    """
    m = content_mask(img, thresh)
    W, H = m.size
    small = m.resize((W, max(1, H // vshrink)), Image.BOX)
    sw, sh = small.size
    px = small.load()
    has = [any(px[x, y] for y in range(sh)) for x in range(sw)]
    runs, start = [], None
    for x in range(sw):
        if has[x] and start is None:
            start = x
        elif not has[x] and start is not None:
            if x - start >= min_w:
                runs.append([start, x])
            start = None
    if start is not None and sw - start >= min_w:
        runs.append([start, sw])
    merged = []
    for a, b in runs:
        if merged and a - merged[-1][1] < vshrink * 2:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return merged


def trim(img, thresh, pad=PAD):
    """裁到内容包围盒（含 pad 白边）。point+getbbox 是纯 C，快几个量级。"""
    box = content_mask(img, thresh).getbbox()
    if not box:
        return img.copy()
    W, H = img.size
    l, t, r, b = box
    return img.crop((max(0, l - pad), max(0, t - pad),
                     min(W, r + pad), min(H, b + pad)))


src, out, idx = sys.argv[1], sys.argv[2], int(sys.argv[3])
img = Image.open(src).convert('RGB')
print('源图 %s  %s' % (os.path.basename(src), img.size))

runs = column_runs(img, BLANK)
print('检测到 %d 栏: %s' % (len(runs), runs))
assert 0 <= idx < len(runs), 'panel_index 越界（共 %d 栏）' % len(runs)

panel = trim(img.crop((runs[idx][0], 0, runs[idx][1], img.size[1])), BLANK)
print('第 %d 栏裁出: %s' % (idx, panel.size))

os.makedirs(os.path.dirname(out), exist_ok=True)
panel.save(out)
print('saved -> %s  (%.2f MB)' % (out, os.path.getsize(out) / 1048576))