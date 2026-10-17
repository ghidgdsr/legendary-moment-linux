# ONNX 模型

这三个模型从用户提供的 APK `传奇一瞬.apk`（包名 `xyz.shuncongci.leica`，v1.0）中提取：

| 文件 | SHA-256 |
|---|---|
| `legendary-1.0-depth.fp16.onnx` | `70a6f853e9cb51d729055e48050b98c31d1bf29e5160d1b774253ce413d18a6d` |
| `legendary-1.0-arnet.fp16.onnx` | `a3aa5fa6a0818f36dbfa4be4dd5471d874cea5981357b7aeb28919954e70d05c` |
| `legendary-1.0-gan.fp16.onnx` | `0cd65fb1215c04261735e6b2fa81c86646208bbf5d9a3339a56df6ee348ebd20` |

这些文件仅用于本地研究与算法移植验证。模型与算法版权归原 App 作者/权利人所有；
本项目与 Leica Camera AG 无关联。请勿将模型或成片用于商业分发。

算法与输入/输出规格见 [`../../docs/pipeline.md`](../../docs/pipeline.md)。
