from __future__ import annotations

import numpy as np

from .types import Planes

GAMMA_SHIFT = 3
LAB_SHIFT = 12
LAB_SHIFT2 = 15
L_SCALE = 296
L_SHIFT = -1336934
TAB = 3072

# sRGB -> XYZ (D65) matrix and white point, from Lab.kt.
_M = np.array(
    [
        0.412453,
        0.35758,
        0.180423,
        0.212671,
        0.71516,
        0.072169,
        0.019334,
        0.119193,
        0.950227,
    ],
    dtype=np.float64,
)
_WP = np.array([0.950456, 1.0, 1.088754], dtype=np.float64)


def _build_tables() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.arange(256, dtype=np.float64) / 255.0
    to_linear = np.where(
        x <= 0.04045, x / 12.92, np.power((0.055 + x) / 1.055, 2.4)
    )
    srgb_tab = np.clip(np.rint(to_linear * 2040.0), 0, 65535).astype(np.int64)

    i = np.arange(TAB, dtype=np.float64)
    x2 = i * 4.901960784313725e-4
    v = np.where(x2 < 0.008856, 7.787 * x2 + 0.13793103448275862, np.cbrt(x2))
    cbrt_tab = np.clip(np.rint(32768.0 * v), 0, 65535).astype(np.int64)

    coeffs = np.rint((4096.0 * _M) / np.repeat(_WP, 3)).astype(np.int64)
    return srgb_tab, cbrt_tab, coeffs


SRGB_TAB, CBRT_TAB, COEFFS = _build_tables()


def _desc(x: np.ndarray, n: int) -> np.ndarray:
    return (x + (1 << (n - 1))) >> n


def _clip8(x: np.ndarray) -> np.ndarray:
    return np.clip(x, 0, 255).astype(np.uint8)


def rgb_to_lab_inplace(p: Planes, block_rows: int = 384) -> None:
    c0, c1, c2, c3, c4, c5, c6, c7, c8 = (int(v) for v in COEFFS)
    h = p.height
    for y0 in range(0, h, block_rows):
        y1 = min(h, y0 + block_rows)
        r = SRGB_TAB[p.p0[y0:y1].astype(np.intp)]
        g = SRGB_TAB[p.p1[y0:y1].astype(np.intp)]
        b = SRGB_TAB[p.p2[y0:y1].astype(np.intp)]
        fx = CBRT_TAB[
            np.clip(_desc(c0 * r + c1 * g + c2 * b, LAB_SHIFT), 0, TAB - 1)
        ]
        fy = CBRT_TAB[
            np.clip(_desc(c3 * r + c4 * g + c5 * b, LAB_SHIFT), 0, TAB - 1)
        ]
        fz = CBRT_TAB[
            np.clip(_desc(c6 * r + c7 * g + c8 * b, LAB_SHIFT), 0, TAB - 1)
        ]
        p.p0[y0:y1] = _clip8(_desc(fy * L_SCALE + L_SHIFT, LAB_SHIFT2))
        p.p1[y0:y1] = _clip8(
            _desc((fx - fy) * 500 + 4194304, LAB_SHIFT2)
        )
        p.p2[y0:y1] = _clip8(
            _desc((fy - fz) * 200 + 4194304, LAB_SHIFT2)
        )


def _gamma(v: np.ndarray) -> np.ndarray:
    x = np.clip(v, 0.0, 1.0)
    return np.where(
        x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1.0 / 2.4) - 0.055
    )


def lab_to_rgb_inplace(p: Planes, block_rows: int = 192) -> None:
    h = p.height
    for y0 in range(0, h, block_rows):
        y1 = min(h, y0 + block_rows)
        l = (p.p0[y0:y1].astype(np.float64) * 100.0) / 255.0
        a = p.p1[y0:y1].astype(np.float64) - 128.0
        b = p.p2[y0:y1].astype(np.float64) - 128.0

        low = l <= 8.0
        yy = np.where(low, l / 903.3, np.power((l + 16.0) / 116.0, 3.0))
        fy = np.where(
            low,
            (l / 903.3) * 7.787 + 0.13793103448275862,
            (l + 16.0) / 116.0,
        )
        fx = a / 500.0 + fy
        fz = fy - b / 200.0

        fx3 = fx * fx * fx
        fz3 = fz * fz * fz
        x = np.where(
            fx3 > 0.008856,
            fx3,
            (fx - 0.13793103448275862) / 7.787,
        ) * 0.950456
        z = np.where(
            fz3 > 0.008856,
            fz3,
            (fz - 0.13793103448275862) / 7.787,
        ) * 1.088754

        r = _gamma(3.240479 * x - 1.53715 * yy - 0.498535 * z) * 255.0
        g = _gamma(-0.969256 * x + 1.875991 * yy + 0.041556 * z) * 255.0
        bl = _gamma(0.055648 * x - 0.204043 * yy + 1.057311 * z) * 255.0

        p.p0[y0:y1] = np.clip(np.rint(r), 0, 255).astype(np.uint8)
        p.p1[y0:y1] = np.clip(np.rint(g), 0, 255).astype(np.uint8)
        p.p2[y0:y1] = np.clip(np.rint(bl), 0, 255).astype(np.uint8)
