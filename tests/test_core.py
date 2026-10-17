from __future__ import annotations

import numpy as np
import pytest

from leica_core import gaussian, lab, legendary, sizes
from leica_core.resample import Filter, resize_planes
from leica_core.types import Frame, Planes


def test_sizes_match_app_constants() -> None:
    assert sizes.COLOR_MAX_PIXELS == 12_500_000
    assert sizes.MODEL_SHORT_EDGE == 1024
    assert sizes.WORK_MAX_SIDE == 2048
    assert sizes.color_size(6000, 4000) == (4330, 2886)
    assert sizes.color_size(4000, 3000) == (4000, 3000)
    assert sizes.model_size(6000, 4000) == (1536, 1024)
    assert sizes.model_size(4000, 6000) == (1024, 1536)
    assert sizes.depth_size(768, 512) == (784, 518)
    assert sizes.working_size(6000, 4000, sizes.BokehOutput.SIZE_2048) == (2048, 1365)
    assert sizes.working_size(6000, 4000, sizes.BokehOutput.ORIGINAL) == (6000, 4000)
    assert sizes.preview_size(4000, 3000, 1280) == (1280, 960)


def _planes(h: int, w: int, seed: int = 0) -> Planes:
    rng = np.random.default_rng(seed)
    return Planes(
        rng.integers(0, 256, (h, w), dtype=np.uint8),
        rng.integers(0, 256, (h, w), dtype=np.uint8),
        rng.integers(0, 256, (h, w), dtype=np.uint8),
    )


def test_resample_identity_and_constant() -> None:
    p = _planes(18, 23, 1)
    same = resize_planes(p, 23, 18, Filter.BICUBIC)
    assert np.array_equal(same.p0, p.p0)
    const = Planes(
        np.full((20, 30), 37, np.uint8),
        np.full((20, 30), 90, np.uint8),
        np.full((20, 30), 200, np.uint8),
    )
    for out_w, out_h in [(15, 10), (45, 60), (30, 20)]:
        out = resize_planes(const, out_w, out_h, Filter.BICUBIC)
        for c in range(3):
            assert int(out.plane(c).min()) == int(out.plane(c).max())
            assert abs(int(out.plane(c)[0, 0]) - int(const.plane(c)[0, 0])) <= 1


def test_lab_roundtrip_is_close() -> None:
    p = _planes(32, 32, 2)
    original = p.copy()
    lab.rgb_to_lab_inplace(p)
    lab.lab_to_rgb_inplace(p)
    diff = np.abs(p.p0.astype(int) - original.p0.astype(int)).mean()
    assert diff < 2.0


def test_gaussian_kernel_and_blur() -> None:
    k = gaussian.kernel(2.0)
    assert len(k) % 2 == 1
    assert abs(float(k.sum()) - 1.0) < 1e-6
    assert np.allclose(k, k[::-1])
    a = np.full((24, 24), 0.25, np.float32)
    b = gaussian.blur(a, 1.0)
    assert b.shape == a.shape
    assert np.allclose(b, 0.25, atol=1e-5)
    impulse = np.zeros((32, 32), np.float32)
    impulse[16, 16] = 1.0
    blurred = gaussian.blur(impulse, 1.0)
    assert abs(float(blurred.sum()) - 1.0) < 1e-5


def test_kernel_and_psf_rows() -> None:
    for radius in (0, 1, 2, 5):
        k = legendary.kernel(radius, 2.0)
        assert abs(float(k.data.sum()) - 1.0) < 1e-5
        assert k.data.shape == (k.w, k.w)
        rows = legendary.psf_rows(k)
        assert rows
        assert float(k.data.min()) >= 0.0
        assert float(k.data.max()) <= 1.0
    # The App's 9-gon PSF is intentionally not 180-degree symmetric.


def test_scatter_convolution_matches_reference() -> None:
    rng = np.random.default_rng(7)
    h, w = 28, 31
    high = Frame(
        (rng.random((3, h, w)) * (rng.random((1, h, w)) > 0.65)).astype(np.float32)
    )
    coc = Frame(rng.integers(0, 5, (1, h, w)).astype(np.float32))
    ref = legendary.scatter_reference(high, coc, 2.0)
    got = legendary.scatter(high, coc, 2.0)
    assert np.allclose(ref.data, got.data, atol=1e-5, rtol=1e-5)


def test_focus_reliability() -> None:
    yy, xx = np.mgrid[0:32, 0:32].astype(np.float32)
    depth = Frame(((xx + yy) / 62.0)[None, :, :])
    value = legendary.focus(depth, (0.5, 0.5))
    assert value is not None
    flat = Frame(np.full((1, 32, 32), 0.5, np.float32))
    assert legendary.focus(flat, (0.5, 0.5)) is None


def test_split_reconstructs_linear_input() -> None:
    p = _planes(16, 16, 3)
    base, high = legendary.split_planes(p)
    rgb = legendary.rgb_from_planes(p)
    lin = legendary.linear(rgb.data)
    recon = legendary.linear(base.data) + high.data
    assert np.allclose(recon, lin, atol=1.5 / 255 + 1e-5)


def test_resize_frame_identity_and_area() -> None:
    rng = np.random.default_rng(4)
    f = Frame(rng.random((3, 17, 21), dtype=np.float32))
    assert legendary.resize_frame(f, 21, 17) is f
    small = legendary.area_frame(f, 7, 9)
    assert small.data.shape == (3, 9, 7)
    assert np.isfinite(small.data).all()
    assert small.data.min() >= f.data.min() - 1e-6
    assert small.data.max() <= f.data.max() + 1e-6


def test_gain_rejects_unknown_aperture() -> None:
    assert legendary.gain(2.0) == 19.44
    with pytest.raises(ValueError):
        legendary.gain(1.4)
