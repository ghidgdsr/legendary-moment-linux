from __future__ import annotations

import numpy as np

try:  # OpenCV is installed in the project venv.
    import cv2
except Exception:  # pragma: no cover - fallback for minimal environments
    cv2 = None


def kernel(sigma: float) -> np.ndarray:
    n = int(round(4.0 * sigma * 2.0 + 1.0)) | 1
    x = np.arange(n, dtype=np.float64) - (n - 1) * 0.5
    d = np.exp((-0.5 / (sigma * sigma)) * x * x)
    d /= d.sum()
    return d.astype(np.float32)


def reflect101(i: int, n: int) -> int:
    if n == 1:
        return 0
    v = i
    while True:
        if 0 <= v < n:
            return v
        if v < 0:
            v = -v
        if v >= n:
            v = (n * 2 - 2) - v


def _fallback_blur(data: np.ndarray, sigma: float) -> np.ndarray:
    k = kernel(sigma)
    r = len(k) // 2
    p = np.pad(data.astype(np.float32), ((0, 0), (r, r)), mode="reflect")
    win = np.lib.stride_tricks.sliding_window_view(p, len(k), axis=1)
    tmp = np.tensordot(win, k, axes=([2], [0])).astype(np.float32)
    p = np.pad(tmp, ((r, r), (0, 0)), mode="reflect")
    win = np.lib.stride_tricks.sliding_window_view(p, len(k), axis=0)
    return np.tensordot(win, k, axes=([2], [0])).astype(np.float32)


def blur(data: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian blur with reflect-101 borders (matches Gaussian.kt)."""
    arr = np.ascontiguousarray(data, dtype=np.float32)
    if sigma <= 0:
        return arr.copy()
    if cv2 is not None:
        k = kernel(sigma)
        return cv2.sepFilter2D(
            arr, -1, k, k, borderType=cv2.BORDER_REFLECT_101
        ).astype(np.float32)
    return _fallback_blur(arr, sigma)
