# 大肥鱼 3D 模型 · 网页查看器

用 three.js 加载大肥鱼（DeepSake）的 3D 模型，在网格地面上自由移动。

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

**界面布局**：左上角标题 + 设置开关；右上角常驻性能仪表（FPS + 三角面数 + 当前画质档位，FPS 按 ≥50 绿 / 25~50 黄 / <25 红 变色）与其下方的**模型精度切换**（150k/45k/15k/5k）；右下角坐标与状态。

右上角开关：相机跟随 / 网格显示 / 线框模式 / **高性能模式** / 转身 180°。

> **高性能模式**（默认开）：`pixelRatio` 锁 1、阴影贴图 1024 —— 帧率优先。关掉则用 `min(devicePixelRatio, 2)` + 2048 阴影，画面更细但更吃 GPU。模型本体 149,686 三角面 / 单材质，集显上建议保持高性能模式。
>
> HUD 状态栏实时显示 FPS（每 0.5s 刷新），卡顿时先看这个数字判断是 GPU 还是页面逻辑瓶颈。

> 缩放范围 `minDistance 1.2` / `maxDistance 40`，地面与网格半径已同步放大到 60，拉到最远也不会看到网格边界。

> 相机默认是 45° 等距视角（沿世界 (1,1,1) 方向，方位角 45°、仰角 35.26°，FOV 40°），无自动旋转。
>
> **角色正面始终面向鼠标指针**：用射线把鼠标位置投影到地面 y=0 平面，角色直接转向该点（无插值、无旋转过程）。移动方向仍按相机朝向计算（第三人称惯例），与朝向解耦——可以横着走、脸朝别处。触屏设备没有指针输入时，回退为朝向移动方向并保留平滑。
>
> **缩放不回弹**：相机跟随只平移 target，不干预相机到 target 的距离（早期版本会把距离往 [3.4, 7.5] 拉，把滚轮调好的缩放推回去）。
手机上会自动出现左半屏虚拟摇杆。

> 「转身 180°」是因为图生3D 模型的正面朝向不固定，若发现角色是倒着走的，点一下这个开关即可。

## 目录结构

```
web/
├── index.html              页面本体（场景/光照/输入/动画都在这里）
├── server.py               本地静态服务器（python3 server.py，控制台打印网址）
├── gen_model.py            图生3D 调用包装（提交+轮询+下载）
├── fetch_result.py         按 job_id 取回模型产物
├── optimize_glb.py         GLB 贴图压缩（4096 PNG → 2048 JPEG）
├── simplify_glb.py         GLB 网格简化（顶点聚类，生成低模）
└── assets/
    ├── dafeiyu.glb         网页用的模型（6.0 MB，15 万面）
    ├── dafeiyu_50k.glb     简化版（2.6 MB，4.5 万面）
    ├── dafeiyu_15k.glb     简化版（1.6 MB，1.5 万面）
    ├── dafeiyu_5k.glb      简化版（1.1 MB，5 千面）
    ├── dafeiyu_hires.glb   原始高模（25.8 MB，4096 贴图）
    ├── dafeiyu_preview.png 服务端渲染的预览图
    ├── three.module.js     three.js r170（本地化，离线可用）
    └── addons/             OrbitControls / GLTFLoader / BufferGeometryUtils
```

## 模型精度档位

页面右上角有 `150k / 45k / 15k / 5k` 四个按钮，可实时切换模型对比帧率。低模由 `simplify_glb.py` 的**顶点聚类**算法生成：

```bash
python3 simplify_glb.py assets/dafeiyu.glb assets/dafeiyu_15k.glb --target 15000
```

原理：把模型空间按三维体素划分，同一体素内的顶点合并，并丢弃退化三角形；体素分辨率二分搜索以逼近目标面数。**UV 量化级数跟随体素分辨率**（否则 UV 桶比体素更细，聚类键永远唯一，等于没简化）。

| 文件 | 顶点 | 三角面 | 体积 |
| --- | --- | --- | --- |
| `dafeiyu.glb` | 108,918 | 149,686 | 6.0 MB |
| `dafeiyu_50k.glb` | 40,751 | 45,388 | 2.6 MB |
| `dafeiyu_15k.glb` | 19,196 | 14,714 | 1.6 MB |
| `dafeiyu_5k.glb` | 9,845 | 4,973 | 1.1 MB |

四档的包围盒几乎一致（0.85 × 1.14 × 0.64），轮廓保持良好。

## 模型信息

| 项目 | 值 |
| --- | --- |
| 来源 | 图生 3D（以三视图裁切的正面图为参考） |
| 面数 | 149,686 三角面 / 108,918 顶点 |
| 材质 | 单材质，4096×4096 烘焙贴图（网页版已降为 2048×2048 JPEG） |
| 朝向 | GLB 根节点自带绕 X 轴 +90° 旋转，GLTFLoader 自动应用后即为「头朝 +Y、正面朝 +Z」的站立姿态；页面**不再叠加任何姿态旋转**，只做落地居中 |
| 缩放 | 页面加载时统一归一化到 1.72 单位高 |

## 二次生成 / 换图

```bash
# 1) 裁一张参考图（>=128px，<=6MB）
# 2) 提交图生3D
python3 gen_model.py <token文件> assets/ref/front.jpg assets
# 3) 若想用原图，重新压缩贴图
python3 optimize_glb.py assets/dafeiyu_hires.glb assets/dafeiyu.glb 2048 88
```

注意：接口不允许同时传提示词和图片，`gen_model.py` 走的是纯图生3D（`prompt=""`）。

## 性能参考

15 万面单网格 + 单张贴图 + 阴影贴图 2042，中端独显笔记本可稳定 60fps。
若要更低配置，可把 `index.html` 里的 `shadow.mapSize` 降到 1024，或进一步压缩贴图到 1024。