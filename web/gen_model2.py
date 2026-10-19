# -*- coding: utf-8 -*-
"""用三视图（整图）重新建模，面数可控。

用法: python3 gen_model2.py <token_file> <image> <outdir> [face_count]
默认 face_count=15000（服务端直出低模，UV 连续，不会出现本地简化导致的贴图碎裂）。

注意: 标准输出/错误都不打印凭证或带签名的产物 URL。
"""
import base64
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

token_file, image_path, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
face_count = int(sys.argv[4]) if len(sys.argv) > 4 else 15000

with open(token_file, "r", encoding="utf-8") as f:
    TOKEN = f.read().strip()
if not TOKEN:
    print("ERROR: empty token", flush=True)
    sys.exit(1)

with open(image_path, "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode()

body = bmg._build_3d_body(
    prompt="",                 # 接口不允许 prompt 与图片同时存在
    model="3.1",
    image_base64=img_b64,
    face_count=face_count,
)

cfg = bmg._PROVIDER_MAP["3d"]
submit = bmg._call_api(bmg._DEFAULT_ENDPOINT, cfg["provider"], cfg["service"],
                       cfg["version"], cfg["submit_action"], body, TOKEN)
job_id = submit.get("JobId")
if not job_id:
    print("ERROR:NO_JOB_ID keys=" + ",".join(sorted(submit.keys())), flush=True)
    sys.exit(1)
print("JOB_SUBMITTED " + job_id, flush=True)

result = bmg._poll_job(bmg._DEFAULT_ENDPOINT, cfg["provider"], cfg["service"],
                       cfg["version"], cfg["query_action"], job_id, TOKEN, 5, 900)
print("JOB_DONE", flush=True)

URL_RE = re.compile(r"https?://\S+")
NAME_BY_EXT = {".glb": "dafeiyu.glb", ".gltf": "dafeiyu.gltf",
               ".obj": "dafeiyu.obj", ".mtl": "dafeiyu.mtl",
               ".png": "dafeiyu_preview.png", ".jpg": "dafeiyu_preview.jpg",
               ".jpeg": "dafeiyu_preview.jpeg"}

urls = []


def walk(obj):
    if isinstance(obj, str):
        if obj.startswith("http"):
            urls.append(obj)
    elif isinstance(obj, list):
        for o in obj:
            walk(o)
    elif isinstance(obj, dict):
        for v in obj.values():
            walk(v)


walk(result)

os.makedirs(outdir, exist_ok=True)
saved, used = [], set()
for url in urls:
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
        saved.append({"name": name, "size": os.path.getsize(dest)})
        print("SAVED %s %d" % (name, os.path.getsize(dest)), flush=True)
    except Exception as e:
        print("FAILED %s %s" % (name, type(e).__name__), flush=True)

with open(os.path.join(outdir, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(saved, f, ensure_ascii=False, indent=2)
print("ALL_DONE " + json.dumps(saved, ensure_ascii=False), flush=True)
