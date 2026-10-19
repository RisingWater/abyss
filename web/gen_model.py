# -*- coding: utf-8 -*-
"""包装 buddy-multimodal-generation：图生3D + 轮询 + 下载产物。
用法: python3 gen_model.py <token_file> <image> <outdir>
注意: 不在标准输出打印任何凭证或签名 URL。
"""
import base64
import importlib.util
import json
import os
import sys
import urllib.request

SCRIPT = ("/opt/WorkBuddy/resources/app.asar.unpacked/resources/plugins/"
          "workbuddy-builtin/skills/buddy-multimodal-generation/scripts/"
          "buddy-multimodal-generation.py")

spec = importlib.util.spec_from_file_location("bmg", SCRIPT)
bmg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bmg)

token_file, image_path, outdir = sys.argv[1], sys.argv[2], sys.argv[3]

with open(token_file, "r", encoding="utf-8") as f:
    TOKEN = f.read().strip()
if not TOKEN:
    print("ERROR: empty token", flush=True)
    sys.exit(1)

with open(image_path, "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode()

body = bmg._build_3d_body(
    # 接口不允许 prompt 与图片同时存在，此处走纯图生3D
    prompt="",
    model="3.1",
    image_base64=img_b64,
    face_count=150000,
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
                       cfg["version"], cfg["query_action"], job_id, TOKEN, 5, 600)
print("JOB_DONE", flush=True)

os.makedirs(outdir, exist_ok=True)
files = result.get("ResultFiles") or result.get("ResultUrls") or []
if isinstance(files, str):
    files = [files]

saved = []
for item in files:
    url = item.get("Url") if isinstance(item, dict) else item
    fmt = (item.get("Type") or item.get("Format") or "") if isinstance(item, dict) else ""
    if not url:
        continue
    ext = os.path.splitext(url.split("?")[0])[1].lower() or ".bin"
    if ext == ".glb":
        name = "dafeiyu.glb"
    elif ext in (".png", ".jpg", ".jpeg"):
        name = "dafeiyu_preview" + ext
    elif ext == ".obj":
        name = "dafeiyu.obj"
    elif ext == ".mtl":
        name = "dafeiyu.mtl"
    else:
        name = "dafeiyu_extra" + ext
    dest = os.path.join(outdir, name)
    urllib.request.urlretrieve(url, dest)
    size = os.path.getsize(dest)
    saved.append({"name": name, "size": size})
    print("SAVED %s %d" % (name, size), flush=True)

with open(os.path.join(outdir, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(saved, f, ensure_ascii=False, indent=2)
print("ALL_DONE", flush=True)