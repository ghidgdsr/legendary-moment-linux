# 传奇一瞬 · Linux 移植

把 Android APK `传奇一瞬.apk`（包名 `xyz.shuncongci.leica`，v1.0）的图片处理链路完整移植到 Linux，
提供局域网 Web 服务：上传照片 → CPU 后端处理 → 前后对比 → 下载成片。

算法依据是反编译源码与三个内置 ONNX 模型，不是近似实现。核心数学（Lab、自定义重采样、
融合、Gaussian、kernel、resize/area、split 等）已通过 JVM 黄金数据对照，详见
[`docs/parity.md`](docs/parity.md)；完整规格见 [`docs/pipeline.md`](docs/pipeline.md)。

## 功能

- 三种处理模式：**仅调色**、**仅虚化**、**调色＋虚化**（与 App 一致）。
- 光圈档位：`f/0.95`、`f/1.8`、`f/2`、`f/2.8`、`f/4`、`f/5.6`。
- 在原图上点击选择对焦点；App 的“焦点深度不可靠”检查也保留。
- 虚化出图尺寸：2048 / 1024 / 原图直出。
- 7 段进度展示、前后滑动对比、下载 PNG、每阶段耗时。
- 局域网共享令牌、单 worker 队列、上传/像素限制、结果 TTL 自动清理。

## 快速开始

```bash
./scripts/setup.sh
./scripts/run.sh
```

仓库已包含 `vendor/models/` 下的三个 ONNX 模型；APK 与反编译源码不在仓库中。
如果本地放入了 `传奇一瞬.apk`，`setup.sh` 会重新从 APK 提取并校验模型；没有 APK 时直接使用
仓库内模型。

启动日志会打印访问令牌；令牌以 `data/token.txt` 为准，首次缺失/为空时才生成一次并写回，
**重启不会改变**。如需主动更换令牌，修改或删除该文件后重启。浏览器打开
`http://<本机局域网IP>:8000`，输入令牌即可。

常用环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `LEICA_TOKEN_FILE` | `data/token.txt` | 令牌文件；存在时始终使用，缺失/为空才生成并写回 |
| `LEICA_HOST` / `LEICA_PORT` | `0.0.0.0` / `8000` | 监听地址与端口 |
| `LEICA_ORT_THREADS` | `min(4, CPU)` | ONNX Runtime CPU 线程数 |
| `LEICA_CACHE_MODELS` | `0` | 设为 `1` 时保留模型会话（更快，但更占内存） |
| `LEICA_MAX_UPLOAD_MB` | `30` | 单文件上传上限 |
| `LEICA_MAX_PIXELS` | `50_000_000` | 输入像素上限 |
| `LEICA_MAX_QUEUE` | `3` | 等待队列长度 |
| `LEICA_JOB_TTL` | `3600` | 结果保留秒数 |
| `LEICA_ALLOW_CIDRS` | 空 | 可选来源网段限制，如 `192.168.1.0/24` |
| `LEICA_DATA_DIR` | `data/jobs` | 任务临时目录 |
| `LEICA_MODEL_DIR` | `vendor/models` | 模型目录 |

## 单图 CLI（调试用）

```bash
.venv/bin/python scripts/cli.py input.jpg output.png \
  --mode COLOR_AND_BLUR --aperture 2.0 \
  --focus-x 0.5 --focus-y 0.5 --output-size SIZE_2048
```

## 项目结构

```text
backend/leica_core/     # 算法移植（不依赖 Web）
  resample.py           # 自定义 Q22 定点重采样
  lab.py                # Lab 色彩空间
  fusion.py             # Lab 域模糊差分融合
  gaussian.py           # reflect-101 高斯模糊
  legendary.py          # CoC/PSF/高光散斑/多尺度/渲染
  sizes.py              # App 尺寸规则
  models.py             # ONNX Runtime 会话与三个模型
  engine.py             # 7 段主链路
  imageio.py            # 解码/EXIF/预览/PNG
backend/app/            # FastAPI、单 worker 队列、令牌鉴权
web/                    # 无构建步骤的前端
tests/                  # Python 单元/API 测试 + JVM 黄金对照
scripts/                # 环境、反编译、CLI、启动
docs/pipeline.md        # 完整算法规格
docs/parity.md          # JVM 对照方法与结果
vendor/models/          # 从 APK 提取的三个 ONNX（本地个人使用）
```

## 处理链路

1. 读取：解码原图，按 App 规则缩放（调色 ≤1250 万像素；虚化长边 2048/1024/原图）。
2. 深度：短边约 518、14 对齐的 DPT/ViT 深度模型；ImageNet 归一化；2%/98% 分位归一化。
3. 上色：GAN 色彩迁移，输入短边 1024，值域 `[-1,1]`。
4. 融合：RGB→Lab，GAN 与原图逐通道差分，Gaussian(σ=25/20) 后回加，再 Lab→RGB。
5. 虚化准备：`(depth-focus)*gain(aperture)` 得到 CoC；PSF/kernel 与高光分离。
6. 虚化模型/高光合成：ARNet（`image` + `defocus`）多尺度渲染；高光用 PSF 卷积散景合成。
7. 成片：sRGB 合成、PNG 编码。

## 验证

```bash
# Python 单元与 API 测试
.venv/bin/python -m pytest -q tests

# 只跑 JVM 数学对照（需先构建 harness）
./scripts/build_parity_harness.sh
.venv/bin/python -m pytest -q tests/test_jvm_parity.py
```

全套测试：**43 passed**（核心数学 10、API 7、模型 I/O 3、JVM 对照 23）。

JVM 对照结果：**23 passed**。其中 Lab 转换、自定义 Resample（BILINEAR/BICUBIC/LANCZOS）、
EXIF 转置逐字节一致；Fusion、Gaussian、kernel、Frame resize、area、normalize、focus、split
在 float32 容差内一致。

注意：JVM 对照所需的 Kotlin/Java 源码由 APK 反编译得到，**未随本仓库分发**。
新克隆仓库运行 `pytest` 时会自动跳过这 23 项；上述结果是在本地准备好
`tests/jvm/harness-src` 后得到的。

如需查看/重新生成反编译源码：`./scripts/decompile.sh`（输出到 `decompiled/app`）。

## 性能（i5-10210U，4 线程，无 GPU）

测试图：3900×2600（约 1010 万像素）。峰值内存为本进程 RSS。

| 模式 | 耗时 | 峰值内存 |
|---|---:|---:|
| 仅调色（原分辨率） | 17.5 s | 1.5 GB |
| 仅虚化（2048 长边） | 31.6 s | 1.9 GB |
| 调色＋虚化（2048 长边） | 42.7–43.1 s | 1.9 GB |

2026-10-17 复测；同一台机器此前一次为 18.1 / 30.8 / 40.6 s，系统负载会让结果有约
5–10% 波动。Web API 端到端（含上传、排队、落盘、轮询）本次约 49 s。模型推理约：
depth 518×784 3.9 s；GAN 1024×1536 5.5 s；ARNet 2048×1365 10.4 s/次（管线阶段还包含
会话加载与多尺度/散景步骤）。
小图会被 App 规则放大到 2048 短边附近处理，因此耗时不一定更短。

## 与 App 的已知差异

- 解码器：Linux 用 Pillow/libjpeg；App 用 Android `BitmapFactory`。不模拟 `inSampleSize`，
  统一全量解码后走同一套自定义重采样。像素源不同，算法一致。
- 执行硬件：App 优先 NNAPI；本移植用 ONNX Runtime CPU。
- PNG：App 使用自研 `NativePng`；Web 端用 Pillow，像素一致、元数据可能不同。
- 并行：App 使用自定义 `parallelFor`；Python 使用 numpy/OpenCV 线程，float32 结果允许极小误差。
- 内存安全：CPU 版本的虚化模式中，“原图直出”限制长边 2048；更大尺寸请选择 2048 / 1024。
  这是为了防止大图 ARNet 推理耗尽内存，不影响 2048/1024 输出与仅调色模式。

## 说明

- 本仓库包含从用户提供的 APK 中提取的三个 ONNX 模型，仅用于算法研究与移植验证。
  模型与算法版权归原 App 作者/权利人所有；本项目与 Leica Camera AG 无关联。
  请勿将模型或成片用于商业分发。
- APK 本身与反编译源码不在仓库中；如需重新反编译，请自行准备 APK 并运行 `scripts/decompile.sh`。
- 前端不依赖 CDN，离线局域网可用。
- 首次运行会下载便携 JDK、jadx、kotlin-stdlib 到 `tools/`（不修改系统）。
