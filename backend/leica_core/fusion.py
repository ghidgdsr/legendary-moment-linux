from __future__ import annotations

import numpy as np

from . import gaussian, lab
from .types import Planes

SIGMA_L = 25.0
SIGMA_AB = 20.0


def fuse(orig: Planes, gan: Planes) -> Planes:
    """Mutates and returns orig, matching Fusion.fuse."""
    if orig.width != gan.width or orig.height != gan.height:
        raise ValueError("size mismatch")
    lab.rgb_to_lab_inplace(orig)
    lab.rgb_to_lab_inplace(gan)
    for c in range(3):
        o = orig.plane(c).astype(np.float32)
        g = gan.plane(c).astype(np.float32)
        diff = g - o
        diff = gaussian.blur(diff, SIGMA_L if c == 0 else SIGMA_AB)
        v = o + diff
        # Kotlin: v<=0 -> 0; v<255 -> (int)v; else 255.
        out = np.where(
            v <= 0.0,
            0.0,
            np.where(v < 255.0, np.trunc(v), 255.0),
        )
        orig.plane(c)[:] = out.astype(np.uint8)
    lab.lab_to_rgb_inplace(orig)
    return orig
