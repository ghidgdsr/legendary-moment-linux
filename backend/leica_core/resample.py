from __future__ import annotations

import math
from enum import Enum

import numpy as np

from .types import Planes

PRECISION_BITS = 22
_FIX = 1 << PRECISION_BITS  # 4194304
_INIT = 1 << (PRECISION_BITS - 1)  # 2097152


class Filter(Enum):
    BILINEAR = 1.0
    BICUBIC = 2.0
    LANCZOS = 3.0

    @property
    def support(self) -> float:
        return self.value


def _weight(filt: Filter, v: np.ndarray) -> np.ndarray:
    x = np.abs(v.astype(np.float64))
    if filt is Filter.BILINEAR:
        return np.where(x < 1.0, 1.0 - x, 0.0)
    if filt is Filter.LANCZOS:
        w = np.sinc(x) * np.sinc(x / 3.0)
        return np.where(x < 3.0, w, 0.0)
    # BICUBIC, a = -0.5
    w1 = ((1.5 * x - 2.5) * x * x) + 1.0
    w2 = ((((x - 5.0) * x + 8.0) * x) - 4.0) * -0.5
    return np.where(x < 1.0, w1, np.where(x < 2.0, w2, 0.0))


class Coeffs:
    __slots__ = ("ksize", "bounds", "kk")

    def __init__(self, ksize: int, bounds: np.ndarray, kk: np.ndarray) -> None:
        self.ksize = ksize
        self.bounds = bounds
        self.kk = kk


def coeffs(in_size: int, out_size: int, filt: Filter) -> Coeffs:
    scale = in_size / out_size
    filter_scale = max(scale, 1.0)
    support = filt.support * filter_scale
    ksize = int(math.ceil(support)) * 2 + 1
    bounds = np.zeros((out_size, 2), dtype=np.int32)
    kk = np.zeros((out_size, ksize), dtype=np.int32)
    ss = 1.0 / filter_scale
    for xx in range(out_size):
        center = (xx + 0.5) * scale
        xmin = int(center - support + 0.5)
        if xmin < 0:
            xmin = 0
        xmax = int(center + support + 0.5)
        if xmax > in_size:
            xmax = in_size
        n = xmax - xmin
        if n <= 0:
            bounds[xx] = (0, 0)
            continue
        positions = np.arange(xmin, xmax, dtype=np.float64)
        w = _weight(filt, (positions - center + 0.5) * ss)
        ww = float(w.sum())
        if ww != 0.0:
            w = w / ww
        fixed = np.where(w < 0.0, w * _FIX - 0.5, w * _FIX + 0.5)
        kk[xx, :n] = np.trunc(fixed).astype(np.int32)
        bounds[xx] = (xmin, n)
    return Coeffs(ksize, bounds, kk)


def _clip8(v: np.ndarray) -> np.ndarray:
    s = np.where(v <= 0, 0, np.minimum(v >> PRECISION_BITS, 255))
    return s.astype(np.uint8)


def _horizontal(src: np.ndarray, out_w: int, c: Coeffs) -> np.ndarray:
    h, _ = src.shape
    out = np.empty((h, out_w), dtype=np.uint8)
    for xx in range(out_w):
        xmin, n = c.bounds[xx]
        if n <= 0:
            out[:, xx] = 0
            continue
        seg = src[:, xmin : xmin + n].astype(np.int64)
        acc = _INIT + seg @ c.kk[xx, :n].astype(np.int64)
        out[:, xx] = _clip8(acc)
    return out


def _vertical(src: np.ndarray, out_h: int, c: Coeffs) -> np.ndarray:
    _, w = src.shape
    out = np.empty((out_h, w), dtype=np.uint8)
    for yy in range(out_h):
        ymin, n = c.bounds[yy]
        if n <= 0:
            out[yy, :] = 0
            continue
        seg = src[ymin : ymin + n, :].astype(np.int64)
        acc = _INIT + c.kk[yy, :n].astype(np.int64) @ seg
        out[yy, :] = _clip8(acc)
    return out


def resize_planes(src: Planes, out_w: int, out_h: int, filt: Filter) -> Planes:
    if not (out_w > 0 and out_h > 0):
        raise ValueError("Failed requirement.")
    planes = []
    changed = False
    for index in range(3):
        arr = src.plane(index)
        cur = arr
        if out_w != src.width:
            cur = _horizontal(cur, out_w, coeffs(src.width, out_w, filt))
            changed = True
        if out_h != src.height:
            cur = _vertical(cur, out_h, coeffs(src.height, out_h, filt))
            changed = True
        planes.append(np.ascontiguousarray(cur) if changed else cur.copy())
    return Planes(planes[0], planes[1], planes[2])
