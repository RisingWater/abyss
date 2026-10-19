# 大肥鱼 3D 模型 · 网页查看器

用 three.js 加载大肥鱼（DeepSake）的 3D 模型，在网格地面上自由移动。

当前模型：**据枪瞄准版单角色低模，14,990 面，1.07 MB**（`assets/dafeiyu_aim_15k.glb`）。

> ⚠️ 换图 / 重新生成前请先读 [「重要：三视图拼图不能用于图生3D」](#重要三视图拼图不能用于图生3d)，
> 这是本项目最容易重复踩的坑。

## 怎么打开

页面用了 ES Module + importmap + GLB 加载，**不能用 `file://` 双击打开**。原因：Chrome 在 `file://` 协议下把所有本地文件视作互不信任的源（origin 为 `null`），`<script type="module">` 和 importmap 的解析、以及 `GLTFLoader` 的 fetch/XHR 请求都会被 CORS 策略直接拒绝 —— 表现就是**白屏 + 控制台一片 CORS / Access-Control-Allow-Origin 报错**。这不是页面代码的问题，是浏览器的安全策略。

页面已内置 `file://` 检测（用普通 `<script>` 在最前面判断，因为 module 脚本在 file 下压根不会执行），双击时会直接弹窗告诉你原因和解决办法。

### 方式一：`python3 server.py`（推荐）

```bash
cd web
python3 server.py
```

控制台会直接打印网页地址，复制到浏览器打开即可。常用参数：

```bash
python3 server.py --port 9000    # 换端口（默认 8899，被占用会自动往后找）
python3 server.py --open         # 启动后自动打开浏览器
python3 server.py --host 0.0.0.0 # 允许同一 WiFi 下手机/其他电脑访问，会同时打印局域网地址
```

`Ctrl+C` 停止。服务器带 `Cache-Control: no-store`，改完代码刷新页面即可生效，不用清缓存。

### 方式二：WorkBuddy 预览面板

在 WorkBuddy 里直接预览本目录的 `index.html`（它自带静态服务）。

### 方式三：分享给同学

```bash
cd web
python3 server.py --host 0.0.0.0
# 同学访问 http://<你控制台打印的局域网IP>:端口/index.html
```

## 操作

| 操作 | 按键 |
| --- | --- |
| 移动 | `W` `A` `S` `D` / 方向键 |
| 疾跑 | `Shift` |
| 转视角 | 鼠标左键拖拽 |
| 缩放 | 滚轮（无阻尼，即时缩放） |
| 平移视角 | 鼠标右键拖拽 |
| 角色朝向 | 始终面向鼠标指针 |
| 声呐扫描（地面扩散环） | `空格` |
| 重置位置 | `R` |

**界面布局**：左上角标题 + 设置开关；右上角常驻性能仪表（FPS + 三角面数 + 当前画质档位，FPS 按 ≥50 绿 / 25~50 黄 / <25 红 变色）；右下角坐标与状态。

右上角开关：相机跟随 / 网格显示 / 线框模式 / **高性能模式** / 转身 180°。

> **高性能模式**（默认开）：`pixelRatio` 锁 1、阴影贴图 1024 —— 帧率优先。关掉则用 `min(devicePixelRatio, 2)` + 2048 阴影，画面更细但更吃 GPU。
>
> HUD 状态栏实时显示 FPS（每 0.5s 刷新），卡顿时先看这个数字判断是 GPU 还是页面逻辑瓶颈。

> 缩放范围 `minDistance 1.2` / `maxDistance 40`，地面与网格半径已同步放大到 60，拉到最远也不会看到网格边界。

> 相机默认是 45° 等距视角（沿世界 (1,1,1) 方向，方位角 45°、仰角 35.26°，FOV 40°），无自动旋转。
>
> **角色正面始终面向鼠标指针**：用射线把鼠标位置投影到地面 y=0 平面，角色直接转向该点（无插值、无旋转过程）。移动方向仍按相机朝向计算（第三人称惯例），与朝向解耦——可以横着走、脸朝别处。触屏设备没有指针输入时，回退为朝向移动方向并保留平滑。
>
> **缩放不回弹**：相机跟随只平移 target，不干预相机到 target 的距离（早期版本会把距离往 [3.4, 7.5] 拉，把滚轮调好的缩放推回去）。
手机上会自动出现左半屏虚拟摇杆。

> 「转身 180°」开关用于手动反转朝向。当前模型实测正面朝 +Z、朝向正确，正常不需要点；换新模型后如果发现角色是倒着走的，点一下即可。

## 目录结构

```
web/
├── index.html              页面本体（场景/光照/输入/动画都在这里）
├── server.py               本地静态服务器（python3 server.py，控制台打印网址）
├── crop_single.py          立绘切栏：按空白列裁出单角色面板（建模样输入）
├── glb_info.py             GLB 体检：面数/根变换/bbox/贴图尺寸，超 15000 面 exit 1
├── render_views.py         离线光栅器渲染六视图，无 GPU 环境确认朝向用
├── gen_model2.py           图生3D 调用包装（可指定面数，提交+轮询+下载）
├── optimize_glb.py         GLB 贴图压缩（4096 PNG → 2048 JPEG）
├── simplify_qem.py         GLB 网格简化（QEM 边塌缩，保护 UV 缝与硬边）
└── assets/
    ├── dafeiyu_aim_15k.glb 网页用的模型（1.07 MB，14990 面，据枪瞄准版）
    ├── three.module.js     three.js r170（本地化，离线可用）
    └── addons/             OrbitControls / GLTFLoader / BufferGeometryUtils
```

## 重要：三视图拼图不能用于图生3D

**实测结论**：把正面/侧面/背面拼成一张整图提交，服务端会把**每一栏当成独立主体各生成一个角色**，而不是融合成一个 3D 角色 —— 结果是两三只大肥鱼并排站在同一个网格里。

早期版本的 `dafeiyu_15k.glb` 就是这么来的（三只），已归档到 `assets/_archive/`。**要单角色模型，只能喂单栏图**。

正确流程：

```bash
# 1) 从参考立绘裁出单栏（按空白列自动切栏 + 裁白边）
python3 crop_single.py \
  ../docs/08-美术资料/02-三视图参考/大肥鱼-据枪瞄准版.png \
  assets/aim_src/front_aim.png 0        # 0 = 左起第一栏（正面）

# 2) 提交图生3D，直出 15000 面（服务端直出，UV 连续，
#    比本地简化更干净）
python3 gen_model2.py <token文件> assets/aim_src/front_aim.png \
  assets/aim_single 15000

# 3) 体检面数与朝向（>15000 面会 exit 1，可直接当验收脚本）
python3 glb_info.py assets/aim_single/dafeiyu.glb

# 4) 无 GPU 环境确认朝向：渲染六视图，肉眼看接触表
python3 render_views.py assets/aim_single/dafeiyu.glb assets/aim_src/views

# 5) 贴图压缩后装进 assets/
python3 optimize_glb.py assets/aim_single/dafeiyu.glb \
  assets/dafeiyu_aim_15k.glb 2048 88
```

> 凭证写在文件里传给脚本，**不要写进命令行**（会进 shell 历史与进程列表）。
> `clientTempToken` 有效期约 30 分钟，401 就是过期，重新取一个写进文件即可。

## 模型信息

| 项目 | 值 |
| --- | --- |
| 来源 | 图生 3D（以据枪瞄准版立绘裁出的单栏正面图为参考） |
| 姿势 | 据枪瞄准，正面对镜头，双手持 M4 |
| 面数 | **14,990 三角面** / 13,607 顶点（≤ 15000 上限） |
| 体积 | 1.07 MB（原始直出 16.86 MB，贴图压缩后） |
| 材质 | 单材质，2048×2048 JPEG 烘焙贴图（原始 4096×4096） |
| 朝向 | GLB 根节点自带绕 X 轴 +90° 旋转，GLTFLoader 自动应用后即为「头朝 +Y、正面朝 +Z」的站立姿态；页面**不再叠加任何姿态旋转**，只做落地居中 |
| 缩放 | 页面加载时统一归一化到 1.72 单位高 |

校验（Node + three r170 真实加载）：高度 1.720 / minY=0 / X 中心 0 / 根四元数 `(0.7071, 0, 0, 0.7071)`。

## 二次生成 / 换图

见上面「重要：三视图拼图不能用于图生3D」的完整流程。

注意：接口不允许同时传提示词和图片，`gen_model2.py` 走的是纯图生3D（`prompt=""`）。
若新模型面数超了上限，用 `simplify_qem.py --target 15000` 做 QEM 边塌缩回收；
顶点聚类方案（`simplify_glb.py`）会把 UV 量化成马赛克导致表面碎裂，不要用来做大幅简化。

## 性能参考

15k 面单网格 + 单张 2048 贴图 + 阴影贴图 2048，中端集显笔记本也能稳定 60fps。
若要更低配置，可把 `index.html` 里的 `shadow.mapSize` 降到 1024，或进一步压缩贴图到 1024。