from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from .types import Frame, Planes

APERTURES = np.array([0.95, 1.8, 2.0, 2.8, 4.0, 5.6], dtype=np.float64)


def gain(aperture: float) -> float:
    if aperture == 0.95:
        return 53.333336
    if aperture == 1.8:
        return 21.6
    if aperture == 2.0:
        return 19.44
    if aperture == 2.8:
        return 15.12
    if aperture == 4.0:
        return 10.8
    if aperture == 5.6:
        return 7.714286
    raise ValueError("不支持的光圈")


# --------------------------------------------------------------------------
# conversions


def rgb_from_planes(p: Planes) -> Frame:
    data = np.empty((3, p.height, p.width), dtype=np.float32)
    for c in range(3):
        data[c] = p.plane(c).astype(np.float32) / 255.0
    return Frame(data)


def planes_from_frame(f: Frame) -> Planes:
    if f.channels != 3 or not np.isfinite(f.data).all():
        raise ValueError("Failed requirement.")
    p = Planes(
        np.empty((f.height, f.width), dtype=np.uint8),
        np.empty((f.height, f.width), dtype=np.uint8),
        np.empty((f.height, f.width), dtype=np.uint8),
    )
    for c in range(3):
        v = np.clip(f.data[c], 0.0, 1.0)
        p.plane(c)[:] = np.rint(v * 255.0).astype(np.uint8)
    return p


# --------------------------------------------------------------------------
# small helpers


def percent(sorted_values: np.ndarray, q: float) -> float:
    n = len(sorted_values)
    x = (n - 1) * q
    i = int(math.floor(x))
    j = min(i + 1, n - 1)
    return float(
        sorted_values[i] * (1.0 - (x - i)) + sorted_values[j] * (x - i)
    )


def normalize(raw: Frame) -> Frame:
    if raw.channels != 1 or not np.isfinite(raw.data).all():
        raise ValueError("Failed requirement.")
    s = np.sort(raw.data.ravel())
    lo = percent(s, 0.02)
    hi = percent(s, 0.98)
    if not (hi - lo >= 1.0e-5):
        raise ValueError("原照片深度无法区分，请更换照片")
    out = np.clip((raw.data - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)
    return Frame(out)


def focus(depth: Frame, point: tuple[float, float]) -> float | None:
    if depth.channels != 1:
        raise ValueError("Failed requirement.")
    data = depth.data[0]
    if not np.isfinite(data).all() or data.min() < 0.0 or data.max() > 1.0:
        raise ValueError("Failed requirement.")
    w, h = depth.width, depth.height
    px, py = point
    x = int(np.rint(px * (w - 1)))
    y = int(np.rint(py * (h - 1)))
    x = min(max(x, 0), w - 1)
    y = min(max(y, 0), h - 1)
    r = int(np.rint(min(w, h) * 0.006))
    r = min(max(r, 1), 8)
    x0 = max(0, x - r)
    x1 = min(w, x + r + 1)
    y0 = max(0, y - r)
    y1 = min(h, y + r + 1)
    values = np.sort(data[y0:y1, x0:x1].ravel())
    med = percent(values, 0.5)
    if (
        percent(values, 0.9) - percent(values, 0.1) <= 0.08
        and abs(data[y, x] - med) <= 0.04
        and float(data.max() - data.min()) > 1.0e-5
    ):
        return med
    return None


def cubic(x: np.ndarray) -> np.ndarray:
    a = np.abs(x.astype(np.float32))
    w1 = ((1.25 * a - 2.25) * a * a) + 1.0
    w2 = ((((-0.75 * a) + 3.75) * a - 6.0) * a) + 3.0
    return np.where(a <= 1.0, w1, np.where(a < 2.0, w2, 0.0)).astype(np.float32)


def linear(x: np.ndarray) -> np.ndarray:
    v = x.astype(np.float64)
    out = np.where(v <= 0.04045, v / 12.92, np.power((0.055 + v) / 1.055, 2.4))
    return out.astype(np.float32)


def srgb(x: np.ndarray) -> np.ndarray:
    v = np.maximum(x.astype(np.float64), 0.0)
    out = np.where(
        v <= 0.0031308,
        v * 12.92,
        np.power(v, 0.41666666) * 1.055 - 0.055,
    )
    return out.astype(np.float32)


def smooth(t: np.ndarray) -> np.ndarray:
    x = np.clip(t, 0.0, 1.0)
    return (x * x * (3.0 - 2.0 * x)).astype(np.float32)


def quantize(x: np.ndarray) -> np.ndarray:
    return (np.rint(np.clip(x, 0.0, 1.0) * 255.0) / 255.0).astype(np.float32)


# --------------------------------------------------------------------------
# Frame resampling (LegendaryMath.resize / area)


def resize_frame(
    f: Frame,
    out_w: int,
    out_h: int,
    bicubic: bool = False,
    align_corners: bool = False,
) -> Frame:
    if out_w == f.width and out_h == f.height:
        return f
    C, H, W = f.data.shape
    y = np.arange(out_h, dtype=np.float32)
    x = np.arange(out_w, dtype=np.float32)
    if align_corners:
        sy = np.zeros_like(y) if out_h == 1 else (y * (H - 1.0)) / (out_h - 1)
        sx = np.zeros_like(x) if out_w == 1 else (x * (W - 1.0)) / (out_w - 1)
    else:
        sy = ((y + 0.5) * H / out_h) - 0.5
        sx = ((x + 0.5) * W / out_w) - 0.5
    iy = np.floor(sy).astype(np.int32)
    ix = np.floor(sx).astype(np.int32)
    fy = (sy - iy).astype(np.float32)
    fx = (sx - ix).astype(np.float32)

    out = np.zeros((C, out_h, out_w), dtype=np.float32)
    if bicubic:
        dys = (-1, 0, 1, 2)
        dxs = (-1, 0, 1, 2)
        wys = [cubic(np.float32(dy) - fy) for dy in dys]
        wxs = [cubic(np.float32(dx) - fx) for dx in dxs]
        for j, dy in enumerate(dys):
            yy = np.clip(iy + dy, 0, H - 1)
            for i, dx in enumerate(dxs):
                xx = np.clip(ix + dx, 0, W - 1)
                weight = (wys[j][:, None] * wxs[i][None, :]).astype(np.float32)
                out += f.data[:, yy[:, None], xx[None, :]] * weight[None, :, :]
    else:
        for j, dy in enumerate((0, 1)):
            yy = np.clip(iy + dy, 0, H - 1)
            wy = (1.0 - fy) if dy == 0 else fy
            for i, dx in enumerate((0, 1)):
                xx = np.clip(ix + dx, 0, W - 1)
                wx = (1.0 - fx) if dx == 0 else fx
                weight = (wy[:, None] * wx[None, :]).astype(np.float32)
                out += f.data[:, yy[:, None], xx[None, :]] * weight[None, :, :]
    return Frame(out)


def area_frame(f: Frame, out_w: int, out_h: int) -> Frame:
    if out_w == f.width and out_h == f.height:
        return f
    C, H, W = f.data.shape
    sx = W / out_w
    tmp = np.empty((C, H, out_w), dtype=np.float64)
    for x in range(out_w):
        xa = x * sx
        xb = (x + 1) * sx
        cols = np.arange(int(math.floor(xa)), int(math.ceil(xb)))
        wcol = np.minimum(xb, cols + 1.0) - np.maximum(xa, cols)
        cols_c = np.clip(cols, 0, W - 1)
        vals = f.data[:, :, cols_c].astype(np.float64)
        tmp[:, :, x] = np.sum(vals * wcol[None, None, :], axis=2) / sx

    sy = H / out_h
    out = np.empty((C, out_h, out_w), dtype=np.float64)
    for y in range(out_h):
        ya = y * sy
        yb = (y + 1) * sy
        rows = np.arange(int(math.floor(ya)), int(math.ceil(yb)))
        wrow = np.minimum(yb, rows + 1.0) - np.maximum(ya, rows)
        rows_c = np.clip(rows, 0, H - 1)
        vals = tmp[:, rows_c, :]
        out[:, y, :] = np.sum(vals * wrow[None, :, None], axis=1) / sy
    return Frame(out.astype(np.float32))


# --------------------------------------------------------------------------
# highlight split


def split_planes(p: Planes) -> tuple[Frame, Frame]:
    rgb = np.empty((3, p.height, p.width), dtype=np.float32)
    for c in range(3):
        rgb[c] = p.plane(c).astype(np.float32) / 255.0
    lin = linear(rgb)
    maxc = np.maximum(np.maximum(lin[0], lin[1]), lin[2])
    ratio = np.minimum(1.0, 0.25 / np.maximum(maxc, 1.0e-8)).astype(np.float32)
    base = np.empty_like(lin)
    high = np.empty_like(lin)
    for c in range(3):
        base[c] = quantize(srgb(lin[c] * ratio))
        high[c] = np.maximum(0.0, lin[c] - linear(base[c]))
    return Frame(base), Frame(high)


# --------------------------------------------------------------------------
# PSF kernel


@dataclass
class Kernel:
    half: int
    data: np.ndarray

    @property
    def w(self) -> int:
        return self.half * 2 + 1


@dataclass
class PsfRow:
    dy: int
    a: int
    b: int
    run: float
    tx: np.ndarray
    tw: np.ndarray
    lo: int
    hi: int


def reflect_one(x0: int, n: int) -> int:
    if n == 1:
        return 0
    x = x0
    while True:
        if 0 <= x < n:
            return x
        x = -x if x < 0 else (n * 2 - 2) - x


def _reflect_array(x: np.ndarray, n: int) -> np.ndarray:
    if n == 1:
        return np.zeros_like(x)
    v = x.astype(np.int64).copy()
    while np.any((v < 0) | (v >= n)):
        v = np.where(v < 0, -v, v)
        v = np.where(v >= n, (n * 2 - 2) - v, v)
    return v.astype(np.int32)


def kernel(radius: int, aperture: float) -> Kernel:
    if radius == 0:
        return Kernel(0, np.ones((1, 1), dtype=np.float32))
    half = int(math.ceil(radius + 0.5))
    w = half * 2 + 1
    if aperture == 0.95:
        roundness = 1.0
    elif aperture == 1.8:
        roundness = 0.85
    elif aperture == 2.0:
        roundness = 0.8
    elif aperture == 2.8:
        roundness = 0.65
    elif aperture == 4.0:
        roundness = 0.45
    else:
        roundness = 0.25

    ss = (np.arange(8, dtype=np.float64) + 0.5) / 8.0
    row = np.arange(w, dtype=np.float64)[:, None, None, None]
    col = np.arange(w, dtype=np.float64)[None, :, None, None]
    dx = (col + ss[None, None, None, :] - 0.5) - half
    dy = (row + ss[None, None, :, None] - 0.5) - half
    theta = np.arctan2(dy, dx)
    period = 40.0 * math.pi / 180.0
    halfperiod = 20.0 * math.pi / 180.0
    sector = (((theta + halfperiod) % period) + period) % period - halfperiod
    polygon = math.cos(halfperiod) / np.cos(sector)
    boundary = radius * (roundness + (1.0 - roundness) * polygon)
    covered = (np.hypot(dx, dy) <= boundary).sum(axis=(2, 3))
    data = (covered / 64.0).astype(np.float32)
    total = float(data.sum())
    if total != 0.0:
        data = data / total
    return Kernel(half, data.astype(np.float32))


def psf_rows(k: Kernel) -> list[PsfRow]:
    full = float(k.data.max())
    rows: list[PsfRow] = []
    w = k.w
    for ky in range(w):
        row = k.data[ky]
        idx = np.flatnonzero(row == full)
        if idx.size:
            a = int(idx[0])
            b = int(idx[-1])
            if not np.all(row[a : b + 1] == full):
                a, b = -1, -2
        else:
            a, b = -1, -2
        outside = np.ones(w, dtype=bool)
        if a >= 0:
            outside[a : b + 1] = False
        tx = np.flatnonzero((row != 0.0) & outside).astype(np.int32)
        tw = row[tx].astype(np.float32)
        if a >= 0 or tx.size:
            lo = min(a if a >= 0 else 2**31 - 1, int(tx.min()) if tx.size else 2**31 - 1)
            hi = max(b, int(tx.max()) if tx.size else -1)
            rows.append(PsfRow(ky - k.half, a, b, full, tx, tw, lo, hi))
    return rows


def scatter_reference(high: Frame, coc: Frame, aperture: float) -> Frame:
    if high.channels != 3 or coc.channels != 1:
        raise ValueError("Failed requirement.")
    H, W = high.height, high.width
    n = H * W
    bins = np.rint(coc.data[0]).astype(np.int32)
    levels = np.unique(bins)
    color = np.zeros((3, H, W), dtype=np.float32)
    coverage = np.zeros((H, W), dtype=np.float32)
    if levels.size == 0:
        return Frame(color)

    min_l = int(levels[0])
    span = int(levels[-1]) - min_l + 1

    def half_of(v: int) -> int:
        return 0 if v == 0 else int(math.ceil(v + 0.5))

    halves = [half_of(abs(int(v))) for v in levels]
    max_half = max(halves)

    present = np.zeros((span, H), dtype=bool)
    yy = np.broadcast_to(np.arange(H, dtype=np.int32)[:, None], (H, W))
    present[bins - min_l, yy] = True

    for level, half in zip(levels, halves):
        level = int(level)
        li = level - min_l
        rows = psf_rows(kernel(abs(level), aperture))
        if not rows:
            continue
        padded = W + half * 2
        col_of = _reflect_array(np.arange(padded, dtype=np.int64) - half, W)
        # prefix sums for each source row that contains this level
        mask_p = np.zeros((H, padded + 1), dtype=np.float32)
        r_p = np.zeros((H, padded + 1), dtype=np.float32)
        g_p = np.zeros((H, padded + 1), dtype=np.float32)
        b_p = np.zeros((H, padded + 1), dtype=np.float32)
        pmin = np.full(H, -1, dtype=np.int32)
        pmax = np.full(H, -1, dtype=np.int32)
        for sy in np.flatnonzero(present[li]):
            sel = bins[sy, col_of] == level
            if not sel.any():
                continue
            sel_f = sel.astype(np.float32)
            vals = high.data[:, sy, col_of]
            np.cumsum(sel_f, out=mask_p[sy, 1:])
            np.cumsum(vals[0] * sel_f, out=r_p[sy, 1:])
            np.cumsum(vals[1] * sel_f, out=g_p[sy, 1:])
            np.cumsum(vals[2] * sel_f, out=b_p[sy, 1:])
            idx = np.flatnonzero(sel)
            pmin[sy] = int(idx[0])
            pmax[sy] = int(idx[-1])

        for y in range(H):
            acc = np.zeros((4, W), dtype=np.float32)
            touched = False
            for row in rows:
                sy = reflect_one(y + row.dy, H)
                if not present[li, sy] or pmin[sy] < 0:
                    continue
                x0 = max(0, int(pmin[sy]) - row.hi)
                x1 = min(W - 1, int(pmax[sy]) - row.lo)
                if x0 > x1:
                    continue
                xs = np.arange(x0, x1 + 1, dtype=np.int32)
                if row.a >= 0:
                    p0 = xs + row.a
                    p1 = xs + row.b + 1
                    acc[0, xs] += row.run * (mask_p[sy, p1] - mask_p[sy, p0])
                    acc[1, xs] += row.run * (r_p[sy, p1] - r_p[sy, p0])
                    acc[2, xs] += row.run * (g_p[sy, p1] - g_p[sy, p0])
                    acc[3, xs] += row.run * (b_p[sy, p1] - b_p[sy, p0])
                    touched = True
                for kx, weight in zip(row.tx, row.tw):
                    src_cols = col_of[xs + int(kx)]
                    sel = bins[sy, src_cols] == level
                    if not sel.any():
                        continue
                    sel_f = sel.astype(np.float32)
                    acc[0, xs] += weight * sel_f
                    vals = high.data[:, sy, src_cols]
                    acc[1:, xs] += vals * (weight * sel_f)[None, :]
                    touched = True
            if not touched:
                continue
            alpha = acc[0]
            nz = alpha != 0.0
            if not nz.any():
                continue
            keep = 1.0 - np.clip(alpha, 0.0, 1.0)
            add = acc[1:]
            color[:, y, :] = np.where(nz[None, :], add + color[:, y, :] * keep[None, :], color[:, y, :])
            coverage[y, :] = np.where(
                nz, np.clip(alpha, 0.0, 1.0) + coverage[y, :] * keep, coverage[y, :]
            )

    out = np.where(
        coverage[None, :, :] > 1.0e-6,
        color / np.maximum(coverage[None, :, :], 1.0e-6),
        0.0,
    )
    return Frame(out.astype(np.float32))


def scatter(high: Frame, coc: Frame, aperture: float) -> Frame:
    """Equivalent to scatter_reference, expressed as one convolution per CoC level.

    The App accumulates, for every destination pixel, kernel-weighted high values of
    source pixels whose rounded CoC equals the level. That is exactly a correlation
    (OpenCV filter2D) of the level-masked high/mask images with the same PSF kernel,
    using reflect-101 borders. The PSF kernel is 180-degree symmetric, so correlation
    and convolution coincide.
    """
    if cv2 is None:
        return scatter_reference(high, coc, aperture)
    if high.channels != 3 or coc.channels != 1:
        raise ValueError("Failed requirement.")
    H, W = high.height, high.width
    bins = np.rint(coc.data[0]).astype(np.int32)
    levels = np.unique(bins)
    color = np.zeros((3, H, W), dtype=np.float32)
    coverage = np.zeros((H, W), dtype=np.float32)
    high_t = np.ascontiguousarray(high.data.transpose(1, 2, 0))
    for level in levels:
        k = kernel(abs(int(level)), aperture).data
        mask = (bins == level).astype(np.float32)
        level_high = high_t * mask[:, :, None]
        acc = cv2.filter2D(
            level_high, -1, k, borderType=cv2.BORDER_REFLECT_101
        ).transpose(2, 0, 1)
        alpha = cv2.filter2D(mask, -1, k, borderType=cv2.BORDER_REFLECT_101)
        clipped = np.clip(alpha, 0.0, 1.0)
        keep = 1.0 - clipped
        color = acc + color * keep[None, :, :]
        coverage = clipped + coverage * keep
    out = np.where(
        coverage[None, :, :] > 1.0e-6,
        color / np.maximum(coverage[None, :, :], 1.0e-6),
        0.0,
    )
    return Frame(out.astype(np.float32))


# --------------------------------------------------------------------------
# multiscale / render


def multiscale(
    rgb: Frame,
    coc: Frame,
    infer: Callable[[Frame, Frame], Frame],
    progress: Callable[[str], None] | None = None,
) -> Frame:
    if rgb.channels != 3 or coc.channels != 1:
        raise ValueError("Failed requirement.")
    target = max(1.0, float(np.abs(coc.data).max()) / 8.0)
    scale = 1.0
    previous = 1.0
    composite: Frame | None = None
    while True:
        w = max(2, int(math.ceil(rgb.width / scale)))
        h = max(2, int(math.ceil(rgb.height / scale)))
        actual = max(rgb.width / w, rgb.height / h)
        small = area_frame(rgb, w, h)
        df = resize_frame(coc, w, h, False, False)
        defocus = np.clip((df.data / actual) / 10.0, -1.0, 1.0).astype(np.float32)
        inferred = infer(small, Frame(defocus))
        if (
            inferred.channels != 3
            or inferred.width != w
            or inferred.height != h
            or not np.isfinite(inferred.data).all()
        ):
            raise ValueError("虚化模型输出异常")
        np.clip(inferred.data, 0.0, 1.0, out=inferred.data)
        enlarged = resize_frame(inferred, rgb.width, rgb.height, False, False)
        if composite is None:
            composite = enlarged
        else:
            weight = smooth((np.abs(coc.data) - 5.0 * previous) / (3.0 * previous))
            composite.data = (
                composite.data * (1.0 - weight) + enlarged.data * weight
            ).astype(np.float32)
        previous = actual
        if scale >= target:
            break
        scale = min(2.0 * scale, target)
    if composite is None:  # pragma: no cover - target >= 1 always runs once
        composite = rgb
    weight = smooth(np.abs(coc.data))
    out = quantize(rgb.data * (1.0 - weight) + composite.data * weight)
    return Frame(out)


def render_coc(
    colored: Planes,
    coc: Frame,
    aperture: float,
    infer: Callable[[Frame, Frame], Frame],
    progress: Callable[[str], None] | None = None,
) -> Planes:
    if (
        coc.width != colored.width
        or coc.height != colored.height
        or coc.channels != 1
    ):
        raise ValueError("Failed requirement.")
    if float(np.abs(coc.data).max()) < 1.0e-6:
        return colored
    if progress:
        progress(f"整图高光分离 {colored.width}×{colored.height}")
    has_highlight = bool(
        (colored.p0 > 136).any() or (colored.p1 > 136).any() or (colored.p2 > 136).any()
    )
    if not has_highlight:
        return planes_from_frame(multiscale(rgb_from_planes(colored), coc, infer, progress))

    base, high = split_planes(colored)
    if not np.any(high.data):
        return planes_from_frame(multiscale(base, coc, infer, progress))

    rendered = multiscale(base, coc, infer, progress)
    if progress:
        progress(f"整图高光散景合成 {colored.width}×{colored.height}")
    optical = scatter(high, coc, aperture)
    rendered.data = srgb(linear(rendered.data) + optical.data)
    if progress:
        progress(f"整图RGB成片转换 {colored.width}×{colored.height}")
    return planes_from_frame(rendered)


def render(
    colored: Planes,
    depth: Frame,
    focus_value: float,
    aperture: float,
    infer: Callable[[Frame, Frame], Frame],
    progress: Callable[[str], None] | None = None,
) -> Planes:
    g = gain(aperture)
    coc0 = Frame(((depth.data - focus_value) * g).astype(np.float32))
    coc = resize_frame(coc0, colored.width, colored.height, False, False)
    return render_coc(colored, coc, aperture, infer, progress)
