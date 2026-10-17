from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Planes:
    """Three uint8 planes (H,W): p0=R, p1=G, p2=B. Alpha is ignored."""

    p0: np.ndarray
    p1: np.ndarray
    p2: np.ndarray

    def __post_init__(self) -> None:
        for name in ("p0", "p1", "p2"):
            arr = getattr(self, name)
            if arr.dtype != np.uint8:
                arr = np.ascontiguousarray(arr, dtype=np.uint8)
                setattr(self, name, arr)
            elif not arr.flags.c_contiguous:
                setattr(self, name, np.ascontiguousarray(arr))
        if self.p0.shape != self.p1.shape or self.p0.shape != self.p2.shape:
            raise ValueError("plane size mismatch")
        if self.p0.ndim != 2 or self.p0.size == 0:
            raise ValueError("invalid plane shape")

    @property
    def width(self) -> int:
        return int(self.p0.shape[1])

    @property
    def height(self) -> int:
        return int(self.p0.shape[0])

    @property
    def size(self) -> int:
        return self.width * self.height

    def plane(self, index: int) -> np.ndarray:
        if index == 0:
            return self.p0
        if index == 1:
            return self.p1
        return self.p2

    def copy(self) -> "Planes":
        return Planes(self.p0.copy(), self.p1.copy(), self.p2.copy())

    @classmethod
    def from_rgb(cls, rgb: np.ndarray) -> "Planes":
        rgb = np.asarray(rgb)
        if rgb.ndim != 3 or rgb.shape[2] < 3:
            raise ValueError("expected HWC RGB array")
        return cls(
            np.ascontiguousarray(rgb[:, :, 0]),
            np.ascontiguousarray(rgb[:, :, 1]),
            np.ascontiguousarray(rgb[:, :, 2]),
        )

    def to_rgb(self) -> np.ndarray:
        return np.stack([self.p0, self.p1, self.p2], axis=2)

    def exif_transposed(self, orientation: int) -> "Planes":
        """Apply the same orientation mapping as Planes.exifTransposed."""
        if not (2 <= orientation < 9):
            return self
        a = self.to_rgb()
        # Mapping from Planes.exifTransposed$lambda$2.
        if orientation == 2:
            out = a[:, ::-1, :]
        elif orientation == 3:
            out = a[::-1, ::-1, :]
        elif orientation == 4:
            out = a[::-1, :, :]
        elif orientation == 5:
            out = np.transpose(a, (1, 0, 2))
        elif orientation == 6:
            out = np.rot90(a, k=-1)
        elif orientation == 7:
            out = np.transpose(np.rot90(a, k=2), (1, 0, 2))
        else:  # 8
            out = np.rot90(a, k=1)
        return Planes.from_rgb(np.ascontiguousarray(out))


@dataclass
class Frame:
    """CHW float32 frame. C is 1 or 3."""

    data: np.ndarray

    def __post_init__(self) -> None:
        arr = np.asarray(self.data, dtype=np.float32)
        if arr.ndim != 3:
            raise ValueError("frame must be CHW")
        if not arr.flags.c_contiguous:
            arr = np.ascontiguousarray(arr)
        self.data = arr

    @property
    def channels(self) -> int:
        return int(self.data.shape[0])

    @property
    def height(self) -> int:
        return int(self.data.shape[1])

    @property
    def width(self) -> int:
        return int(self.data.shape[2])

    @property
    def size(self) -> int:
        return self.width * self.height

    @classmethod
    def zeros(cls, channels: int, width: int, height: int) -> "Frame":
        return cls(np.zeros((channels, height, width), dtype=np.float32))

    def copy(self) -> "Frame":
        return Frame(self.data.copy())
