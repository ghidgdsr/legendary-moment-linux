from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np

from .types import Frame, Planes

MODEL_FILES = {
    "depth": "legendary-1.0-depth.fp16.onnx",
    "arnet": "legendary-1.0-arnet.fp16.onnx",
    "gan": "legendary-1.0-gan.fp16.onnx",
}

MODEL_SHA256 = {
    "depth": "70a6f853e9cb51d729055e48050b98c31d1bf29e5160d1b774253ce413d18a6d",
    "arnet": "a3aa5fa6a0818f36dbfa4be4dd5471d874cea5981357b7aeb28919954e70d05c",
    "gan": "0cd65fb1215c04261735e6b2fa81c86646208bbf5d9a3339a56df6ee348ebd20",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ModelManager:
    def __init__(self, model_dir: str | Path | None = None, threads: int | None = None) -> None:
        root = Path(__file__).resolve().parents[2]
        self.model_dir = Path(
            model_dir or os.environ.get("LEICA_MODEL_DIR", root / "vendor" / "models")
        )
        self.threads = threads or int(
            os.environ.get("LEICA_ORT_THREADS", max(1, min(4, os.cpu_count() or 1)))
        )
        self.cache_models = os.environ.get("LEICA_CACHE_MODELS", "0") == "1"
        self._sessions: dict[str, object] = {}
        self._ort = None

    @property
    def ort(self):
        if self._ort is None:
            import onnxruntime as ort

            self._ort = ort
        return self._ort

    def _session(self, key: str):
        if key in self._sessions:
            return self._sessions[key]
        path = self.model_dir / MODEL_FILES[key]
        if not path.is_file():
            raise FileNotFoundError(f"模型不存在: {path}")
        digest = _sha256(path)
        if digest != MODEL_SHA256[key]:
            raise ValueError(f"内置模型校验失败: {path.name}")
        ort = self.ort
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = self.threads
        opts.inter_op_num_threads = 1
        opts.log_severity_level = 3
        session = ort.InferenceSession(
            str(path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self._sessions[key] = session
        return session

    def close_model(self, key: str) -> None:
        self._sessions.pop(key, None)
        import gc

        gc.collect()

    def close(self) -> None:
        self._sessions.clear()
        import gc

        gc.collect()

    # ------------------------------------------------------------------
    def run_depth(self, frame: Frame) -> Frame:
        session = self._session("depth")
        arr = np.ascontiguousarray(frame.data[None, ...], dtype=np.float32)
        out = session.run(None, {"input": arr})[0]
        out = np.asarray(out, dtype=np.float32)
        while out.ndim > 2 and out.shape[0] == 1:
            out = out[0]
        if out.ndim != 2 or not np.isfinite(out).all():
            raise ValueError("模型输出尺寸异常")
        return Frame(out[None, ...].copy())

    def run_gan(self, planes: Planes) -> Planes:
        session = self._session("gan")
        h, w = planes.height, planes.width
        arr = np.empty((1, 3, h, w), dtype=np.float32)
        for c in range(3):
            arr[0, c] = (planes.plane(c).astype(np.float32) / 255.0 - 0.5) / 0.5
        out = np.asarray(session.run(None, {"input": arr})[0], dtype=np.float32)
        if out.shape != (1, 3, h, w):
            raise ValueError(
                "模型输出尺寸异常: " + "x".join(str(v) for v in out.shape)
            )
        data = out[0]
        if not np.isfinite(data).all():
            raise ValueError("虚化模型输出异常")
        rgb = np.clip(data * 0.5 + 0.5, 0.0, 1.0) * 255.0
        rgb = rgb.astype(np.uint8)  # Kotlin byte cast truncates toward zero
        return Planes(
            np.ascontiguousarray(rgb[0]),
            np.ascontiguousarray(rgb[1]),
            np.ascontiguousarray(rgb[2]),
        )

    def run_arnet(self, image: Frame, defocus: Frame) -> Frame:
        session = self._session("arnet")
        if image.channels != 3 or defocus.channels != 1:
            raise ValueError("Failed requirement.")
        if image.width != defocus.width or image.height != defocus.height:
            raise ValueError("Failed requirement.")
        feeds = {
            "image": np.ascontiguousarray(image.data[None, ...], dtype=np.float32),
            "defocus": np.ascontiguousarray(defocus.data[None, ...], dtype=np.float32),
        }
        out = np.asarray(session.run(None, feeds)[0], dtype=np.float32)
        if out.ndim != 4 or out.shape[0] != 1 or out.shape[1] != 3:
            raise ValueError("模型输出尺寸异常")
        data = out[0]
        if data.shape[1:] != (image.height, image.width):
            raise ValueError("模型输出尺寸异常")
        if not np.isfinite(data).all():
            raise ValueError("Failed requirement.")
        return Frame(data.copy())

    def benchmark(self, size: int = 64) -> dict[str, float]:
        import time

        result: dict[str, float] = {}
        depth_in = Frame(np.zeros((3, size, size), dtype=np.float32))
        t0 = time.perf_counter()
        self.run_depth(depth_in)
        result["depth"] = time.perf_counter() - t0

        gan_in = Planes(
            np.zeros((size, size), np.uint8),
            np.zeros((size, size), np.uint8),
            np.zeros((size, size), np.uint8),
        )
        t0 = time.perf_counter()
        self.run_gan(gan_in)
        result["gan"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        self.run_arnet(depth_in, Frame(np.zeros((1, size, size), np.float32)))
        result["arnet"] = time.perf_counter() - t0
        return result
