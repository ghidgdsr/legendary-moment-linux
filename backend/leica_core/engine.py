from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import legendary
from .fusion import fuse
from .imageio import decode_image, encode_png
from .legendary import (
    focus as depth_focus,
    normalize,
    resize_frame,
    rgb_from_planes,
)
from .models import ModelManager
from .resample import Filter, resize_planes
from .sizes import (
    BokehOutput,
    ProcessingMode,
    depth_size,
    model_size,
    processing_size,
)
from .types import Frame, Planes

ProgressFn = Callable[[str, str], None]


def _noop(stage: str, message: str) -> None:
    return None


@dataclass
class ProcessOptions:
    mode: ProcessingMode
    aperture: float = 2.0
    focus: tuple[float, float] | None = None
    output_size: BokehOutput = BokehOutput.SIZE_2048


@dataclass
class ProcessResult:
    image: bytes
    width: int
    height: int
    mode: ProcessingMode
    aperture: float
    output_size: BokehOutput
    focus: float | None
    rendered: bool
    downscaled: bool
    reason: str
    timings: dict[str, float] = field(default_factory=dict)


class LeicaEngine:
    def __init__(
        self,
        model_dir: str | None = None,
        threads: int | None = None,
    ) -> None:
        self.models = ModelManager(model_dir, threads)
        self.timings: dict[str, float] = {}

    def close(self) -> None:
        self.models.close()

    # ------------------------------------------------------------------
    def _depth(self, work: Planes) -> Frame:
        scale = min(1.0, 768.0 / max(work.width, work.height))
        aw = max(1, int(work.width * scale))
        ah = max(1, int(work.height * scale))
        analysis = resize_planes(work, aw, ah, Filter.LANCZOS)
        dw, dh = depth_size(aw, ah)
        inp = resize_frame(
            rgb_from_planes(analysis), dw, dh, bicubic=True, align_corners=False
        )
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        for c in range(3):
            inp.data[c] = (inp.data[c] - mean[c]) / std[c]
        raw = self.models.run_depth(inp)
        raw = resize_frame(raw, aw, ah, bicubic=False, align_corners=True)
        return normalize(raw)

    # ------------------------------------------------------------------
    def process_bytes(
        self,
        data: bytes,
        options: ProcessOptions,
        progress: ProgressFn = _noop,
    ) -> ProcessResult:
        mode = options.mode
        aperture = float(options.aperture)
        legendary.gain(aperture)  # validate aperture
        if mode.blur_enabled and options.focus is None:
            raise ValueError("请先在原照片上点击焦点")

        self.timings = {}
        t_all = time.perf_counter()

        # ---- 1/7 read ------------------------------------------------
        t0 = time.perf_counter()
        if mode.blur_enabled:
            progress("read", f"1/7 读取 · {options.output_size.label} · CPU")
        else:
            progress("read", "1/7 读取 · ≤1250万像素 · CPU")
        src = decode_image(data)
        sw, sh = src.width, src.height
        w, h = processing_size(sw, sh, mode.blur_enabled, options.output_size)
        self.timings["read"] = time.perf_counter() - t0

        work: Planes | None = None
        depth_map: Frame | None = None

        if mode.blur_enabled:
            t0 = time.perf_counter()
            work = resize_planes(src, w, h, Filter.BICUBIC)
            progress("depth", f"2/7 深度 · {w}×{h} · 执行中")
            depth_map = self._depth(work)
            if not self.models.cache_models:
                self.models.close_model("depth")
            self.timings["depth"] = time.perf_counter() - t0

        selected_focus: float | None = None
        if depth_map is not None and options.focus is not None:
            selected_focus = depth_focus(depth_map, options.focus)

        # ---- 3/7 color / blur-only ----------------------------------
        colored: Planes
        downscaled: bool
        if mode.color_enabled:
            mw, mh = model_size(sw, sh)
            t0 = time.perf_counter()
            progress("color", f"3/7 上色 · {mw}×{mh} · 执行中")
            gan = self.models.run_gan(resize_planes(src, mw, mh, Filter.BILINEAR))
            if not self.models.cache_models:
                self.models.close_model("gan")
            self.timings["color"] = time.perf_counter() - t0

            t0 = time.perf_counter()
            progress("fuse", f"4/7 融合 · {w}×{h} · CPU")
            original = work if work is not None else resize_planes(src, w, h, Filter.BICUBIC)
            if original.width != w or original.height != h:
                raise AssertionError("prepare size mismatch")
            colored = fuse(original, resize_planes(gan, w, h, Filter.BICUBIC))
            self.timings["fuse"] = time.perf_counter() - t0
            if mode.blur_enabled:
                edge = options.output_size.long_edge
                downscaled = edge is not None and max(sw, sh) > edge
            else:
                downscaled = (w, h) != (sw, sh)
        else:
            if work is None:
                raise AssertionError("missing working image")
            if work.width != w or work.height != h:
                raise AssertionError("prepare size mismatch")
            progress("color_skip", "3/7 仅虚化 · 跳过调色模型与色彩融合")
            progress("fuse_skip", f"4/7 保留原照片色彩 · {w}×{h} · CPU")
            colored = work
            edge = options.output_size.long_edge
            downscaled = edge is not None and max(sw, sh) > edge

        # src is no longer needed; free the full-resolution decode.
        src = None  # type: ignore[assignment]
        w, h = colored.width, colored.height

        # ---- 5/7 + 6/7 render ---------------------------------------
        rendered = bool(mode.blur_enabled and selected_focus is not None)
        if rendered:
            t0 = time.perf_counter()
            progress("render_prep", f"5/7 虚化准备 · {w}×{h} · CPU")

            def infer_cb(image: Frame, defocus: Frame) -> Frame:
                progress(
                    "render_model",
                    f"6/7 虚化模型 · {image.width}×{image.height} · 执行中",
                )
                return self.models.run_arnet(image, defocus)

            def sub_progress(message: str) -> None:
                if "高光散景合成" in message:
                    progress("highlight", f"6/7 高光合成 · {w}×{h} · CPU")
                elif "RGB成片转换" in message:
                    progress("color_convert", f"6/7 颜色转换 · {w}×{h} · CPU")
                else:
                    progress("render_prep", f"5/7 虚化准备 · {w}×{h} · CPU")

            assert depth_map is not None and selected_focus is not None
            output = legendary.render(
                colored,
                depth_map,
                selected_focus,
                aperture,
                infer_cb,
                sub_progress,
            )
            if not self.models.cache_models:
                self.models.close_model("arnet")
            self.timings["render"] = time.perf_counter() - t0
        else:
            output = colored

        # ---- 7/7 encode ---------------------------------------------
        t0 = time.perf_counter()
        progress("encode", f"7/7 成片 · {output.width}×{output.height} · CPU")
        png = encode_png(output)
        self.timings["encode"] = time.perf_counter() - t0

        if mode.blur_enabled:
            if rendered:
                reason = f"{mode.label} · {options.output_size.label} · 整图虚化"
            elif mode.color_enabled:
                reason = "焦点深度不可靠；已上色但未虚化，请在目标内部重新点选。"
            else:
                reason = "焦点深度不可靠；未调色且未虚化，请在目标内部重新点选。"
        elif downscaled:
            reason = (
                "未启用虚化；照片超过1250万像素，按1250万像素 "
                f"{output.width}×{output.height} 色彩迁移；不加载深度/虚化模型。"
            )
        else:
            reason = "未启用虚化；仅色彩迁移，保留原照片细节与原分辨率；不加载深度/虚化模型。"

        self.timings["total"] = time.perf_counter() - t_all
        return ProcessResult(
            image=png,
            width=output.width,
            height=output.height,
            mode=mode,
            aperture=aperture,
            output_size=options.output_size,
            focus=selected_focus,
            rendered=rendered,
            downscaled=downscaled,
            reason=reason,
            timings=dict(self.timings),
        )
