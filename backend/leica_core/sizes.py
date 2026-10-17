from __future__ import annotations

import math
from enum import Enum

MODEL_SHORT_EDGE = 1024
WORK_MAX_SIDE = 2048
PREVIEW_MAX_SIDE = 1280
COLOR_MAX_PIXELS = 12_500_000


class BokehOutput(Enum):
    ORIGINAL = ("原图直出", None)
    SIZE_2048 = ("降低至2048出图", WORK_MAX_SIDE)
    SIZE_1024 = ("降低至1024出图", MODEL_SHORT_EDGE)

    @property
    def label(self) -> str:
        return self.value[0]

    @property
    def long_edge(self) -> int | None:
        return self.value[1]


class ProcessingMode(Enum):
    COLOR_ONLY = ("仅调色", True, False)
    BLUR_ONLY = ("仅虚化", False, True)
    COLOR_AND_BLUR = ("调色＋虚化", True, True)

    @property
    def label(self) -> str:
        return self.value[0]

    @property
    def color_enabled(self) -> bool:
        return self.value[1]

    @property
    def blur_enabled(self) -> bool:
        return self.value[2]

    @classmethod
    def from_flags(cls, color: bool, blur: bool) -> "ProcessingMode":
        for mode in cls:
            if mode.color_enabled == color and mode.blur_enabled == blur:
                return mode
        raise ValueError("请至少选择调色或虚化")


def color_size(width: int, height: int) -> tuple[int, int]:
    if not (width > 0 and height > 0):
        raise ValueError("Failed requirement.")
    px = width * height
    if px <= COLOR_MAX_PIXELS:
        return width, height
    s = math.sqrt(COLOR_MAX_PIXELS / px)
    w = max(1, int(width * s))
    h = max(1, int(height * s))
    while w * h > COLOR_MAX_PIXELS:
        if w >= h:
            w -= 1
        else:
            h -= 1
    return w, h


def color_sample(width: int, height: int) -> int:
    tw, th = color_size(width, height)
    sample = 1
    while width // (sample * 2) >= tw and height // (sample * 2) >= th:
        sample *= 2
    return sample


def working_size(width: int, height: int, output: BokehOutput) -> tuple[int, int]:
    edge = output.long_edge
    if edge is None:
        return width, height
    m = max(width, height)

    def fitted(n: int) -> int:
        return max(1, (n * edge + m // 2) // m)

    return fitted(width), fitted(height)


def processing_size(
    width: int, height: int, blur_enabled: bool, output: BokehOutput
) -> tuple[int, int]:
    if blur_enabled:
        return working_size(width, height, output)
    return color_size(width, height)


def model_size(width: int, height: int) -> tuple[int, int]:
    if not (width > 0 and height > 0):
        raise ValueError("Failed requirement.")
    new_long = int(max(width, height) * 1024 / min(width, height))
    if width <= height:
        return MODEL_SHORT_EDGE, new_long
    return new_long, MODEL_SHORT_EDGE


def gan_sample(width: int, height: int) -> int:
    if not (width > 0 and height > 0):
        raise ValueError("Failed requirement.")
    sample = 1
    while (min(width, height) // sample) // 2 >= 1024:
        sample *= 2
    return sample


def working_sample(width: int, height: int, output: BokehOutput) -> int:
    edge = output.long_edge
    if edge is None:
        return 1
    sample = 1
    while (max(width, height) // sample) // 2 >= edge:
        sample *= 2
    return sample


def depth_size(width: int, height: int) -> tuple[int, int]:
    if not (width > 0 and height > 0):
        raise ValueError("Failed requirement.")
    desired = 518.0 / min(width, height)
    factor = min(desired, 2044.0 / max(width, height))

    def dim(n: int) -> int:
        return min(2044, max(14, int(round((n * factor) / 14.0)) * 14))

    return dim(width), dim(height)


def preview_size(width: int, height: int, max_side: int = PREVIEW_MAX_SIDE) -> tuple[int, int]:
    longest = max(width, height)
    if longest <= max_side:
        return width, height
    s = max_side / longest
    return max(1, int(width * s)), max(1, int(height * s))
