# JVM 黄金数据对照

目标：在没有 Android 设备/模拟器的情况下，验证 Python 移植与 App 的 Kotlin 数学一致。

## 方法

1. 用 jadx 1.5.6 反编译 `classes3.dex`，得到可读的 Kotlin→Java 源码（`decompiled/app`）。
2. 对控制流复杂、jadx 生成不可编译循环的 `LegendaryMath`，另用 dex2jar 2.4 + CFR 0.152
   反编译；修补反编译器无法推断的局部类型/无法结构的 goto。
3. 只保留纯数学类：`Lab`、`Fusion`、`Gaussian`、`Resample`、`Planes`、`LegendaryMath`、`Cancel`。
4. `LeicaCoreKt.parallelFor` 用顺序执行的 JVM stub 替代；数学按行/通道独立，顺序执行不改变结果。
5. 由于 CFR 仍无法完整还原 `multiscale`、`render`、`renderCoc`、`scatter$app_debug`，harness 中
   这四个方法替换为抛异常的 stub。它们由 Python 端实现与端到端出图覆盖；`scatter` 的卷积改写
   另与逐行前缀和参考实现做了数值对照（最大误差 ~1e-7）。
6. `tests/jvm/Parity.java` 通过二进制文件交换 Planes/Frame：
   - Planes：`int32 w,h` + `p0,p1,p2` 原始字节（大端）。
   - Frame：`int32 w,h,c` + `float32 CHW`（大端）。
   - kernel：`int32 half,w` + `float32 w*w`。
7. `tests/test_jvm_parity.py` 生成输入、调用 JVM、读回输出并与 Python 结果比较。

## 构建与运行

```bash
./scripts/build_parity_harness.sh
.venv/bin/python -m pytest -q tests/test_jvm_parity.py
```

结果：**23 passed**。

## 覆盖项与容差

| 测试 | 尺寸/参数 | 判定 |
|---|---|---|
| Lab RGB→Lab | 32×24 随机 | **逐字节一致** |
| Lab→RGB | 32×24 随机 | 每通道最大误差 ≤ 1 |
| Fusion.fuse | 24×20 随机 | 平均误差 ≤ 0.5，最大 ≤ 4 |
| Resample BILINEAR | 23×17 → 31×12 | **逐字节一致** |
| Resample BICUBIC | 同上 | **逐字节一致** |
| Resample LANCZOS | 同上 | **逐字节一致** |
| Gaussian.blur | 18×22，σ=2.0 | `atol=2e-5` |
| kernel(radius=5, f/2.0) | 13×13 | `atol=1e-6` |
| Frame resize（4 种 cubic/align 组合） | 17×21 → 9×13 | `atol=2e-5` |
| area 降采样 | 20×24 → 7×9 | `atol=2e-5` |
| normalize | 16×16 随机 | `atol=1e-6` |
| focus | 32×32 梯度，中心点 | 标量差 < 1e-6 |
| EXIF 转置 orientation 2..8 | 10×7 随机 | **逐字节一致** |
| split（高光分离） | 16×16 随机 | `atol=2e-5` |

## 说明

- 模型推理不参与 JVM 对照：Python 与 App 使用同一批 ONNX 文件，输入/输出张量构造逻辑已由
  `tests/test_models.py` 的 I/O 检查与端到端出图覆盖。
- `multiscale` 的多尺度权重、`renderCoc` 的高光分支与最终 sRGB 合成属于编排逻辑，已逐行移植；
  JVM harness 不覆盖，原因见上。
- 运行 harness 需要 `tools/jdk` 与 `tools/kotlin-stdlib.jar`；`scripts/setup.sh` 会自动准备。
- **分发说明**：harness 使用的 Kotlin/Java 源码由 APK 反编译得到，未随公开仓库分发；
  `tests/jvm/harness-src` 只存在于本地逆向工作区。新克隆的仓库运行 `pytest` 时，
  `tests/test_jvm_parity.py` 会自动跳过；上面 23 项通过是在本地准备好 harness 后的结果。
