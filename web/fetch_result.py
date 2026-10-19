# -*- coding: utf-8 -*-
"""查询已完成的 3D 任务并下载产物（自动探测 URL 字段，输出做脱敏）。
用法: python3 fetch_result.py <token_file> <job_id> <outdir>
"""
import importlib.util
import json
import os
import re
import sys
import urllib.request

SCRIPT = ("/opt/WorkBuddy/resources/app.asar.unpacked/resources/plugins/"
          "workbuddy-builtin/skills/buddy-multimodal-generation/scripts/"
          "buddy-multimodal-generation.py")
spec = importlib.util.spec_from_file_location("bmg", SCRIPT)
bmg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bmg)

token_file, job_id, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
with open(token_file, encoding="utf-8") as f:
    TOKEN = f.read().strip()

cfg = bmg._PROVIDER_MAP["3d"]
result = bmg._call_api(bmg._DEFAULT_ENDPOINT, cfg["provider"], cfg["service"],
                       cfg["version"], cfg["query_action"], {"JobId": job_id}, TOKEN)

URL_RE = re.compile(r"https?://\S+")


def mask(obj):
    if isinstance(obj, str):
        return URL_RE.sub("<url>", obj)
    if isinstance(obj, list):
        return [mask(o) for o in obj]
    if isinstance(obj, dict):
        return {k: mask(v) for k, v in obj.items()}
    return obj


print("STRUCTURE=" + json.dumps(mask(result), ensure_ascii=False)[:4000], flush=True)

urls = []


def walk(obj, key_hint=""):
    if isinstance(obj, str):
        if obj.startswith("http"):
            urls.append((key_hint, obj))
    elif isinstance(obj, list):
        for o in obj:
            walk(o, key_hint)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            walk(v, k)


walk(result)

NAME_BY_EXT = {".glb": "dafeiyu.glb", ".gltf": "dafeiyu.gltf", ".obj": "dafeiyu.obj",
               ".mtl": "dafeiyu.mtl", ".png": "dafeiyu_preview.png",
               ".jpg": "dafeiyu_preview.jpg", ".jpeg": "dafeiyu_preview.jpeg",
               ".fbx": "dafeiyu.fbx", ".usdz": "dafeiyu.usdz", ".stl": "dafeiyu.stl"}

os.makedirs(outdir, exist_ok=True)
saved = []
used = set()
for hint, url in urls:
    ext = os.path.splitext(url.split("?")[0])[1].lower()
    if ext not in NAME_BY_EXT:
        continue
    name = NAME_BY_EXT[ext]
    if name in used:
        continue
    used.add(name)
    dest = os.path.join(outdir, name)
    try:
        urllib.request.urlretrieve(url, dest)
        size = os.path.getsize(dest)
        saved.append({"name": name, "size": size, "hint": hint})
        print("SAVED %s %d bytes" % (name, size), flush=True)
    except Exception as e:
        print("FAILED %s %s" % (name, type(e).__name__), flush=True)

with open(os.path.join(outdir, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(saved, f, ensure_ascii=False, indent=2)
print("ALL_DONE " + json.dumps(saved, ensure_ascii=False), flush=True)