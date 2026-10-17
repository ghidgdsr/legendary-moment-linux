from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest

from leica_core import fusion, gaussian, lab, legendary
from leica_core.resample import Filter, resize_planes
from leica_core.types import Frame, Planes

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "tools" / "jdk" / "bin" / "java"
STDLIB = ROOT / "tools" / "kotlin-stdlib.jar"
CLASSES = ROOT / "tests" / "jvm" / "harness-classes"

pytestmark = pytest.mark.skipif(
    not (JAVA.is_file() and STDLIB.is_file() and (CLASSES / "Parity.class").is_file()),
    reason="JVM parity harness is not built (run the commands in README/docs)",
)


def run_java(*args: str) -> None:
    subprocess.run(
        [
            str(JAVA),
            "-cp",
            f"{CLASSES}:{STDLIB}",
            "Parity",
            *map(str, args),
        ],
        check=True,
        capture_output=True,
    )


def write_planes(path: Path, p: Planes) -> None:
    with path.open("wb") as fh:
        fh.write(struct.pack(">ii", p.width, p.height))
        fh.write(p.p0.tobytes())
        fh.write(p.p1.tobytes())
        fh.write(p.p2.tobytes())


def read_planes(path: Path) -> Planes:
    with path.open("rb") as fh:
        w, h = struct.unpack(">ii", fh.read(8))
        n = w * h
        p0 = np.frombuffer(fh.read(n), dtype=np.uint8).reshape(h, w).copy()
        p1 = np.frombuffer(fh.read(n), dtype=np.uint8).reshape(h, w).copy()
        p2 = np.frombuffer(fh.read(n), dtype=np.uint8).reshape(h, w).copy()
    return Planes(p0, p1, p2)


def write_frame(path: Path, f: Frame) -> None:
    with path.open("wb") as fh:
        fh.write(struct.pack(">iii", f.width, f.height, f.channels))
        fh.write(f.data.astype(">f4").tobytes())


def read_frame(path: Path) -> Frame:
    with path.open("rb") as fh:
        w, h, c = struct.unpack(">iii", fh.read(12))
        data = np.frombuffer(fh.read(w * h * c * 4), dtype=">f4").astype(np.float32)
    return Frame(data.reshape(c, h, w).copy())


def read_kernel(path: Path) -> np.ndarray:
    with path.open("rb") as fh:
        _half, w = struct.unpack(">ii", fh.read(8))
        data = np.frombuffer(fh.read(w * w * 4), dtype=">f4").astype(np.float32)
    return data.reshape(w, w)


def random_planes(h: int, w: int, seed: int) -> Planes:
    rng = np.random.default_rng(seed)
    return Planes(
        rng.integers(0, 256, (h, w), dtype=np.uint8),
        rng.integers(0, 256, (h, w), dtype=np.uint8),
        rng.integers(0, 256, (h, w), dtype=np.uint8),
    )


def random_frame(c: int, h: int, w: int, seed: int) -> Frame:
    rng = np.random.default_rng(seed)
    return Frame(rng.random((c, h, w), dtype=np.float32))


def test_lab_matches(tmp_path: Path) -> None:
    p = random_planes(24, 32, 10)
    pin = tmp_path / "in.bin"
    pout = tmp_path / "out.bin"
    write_planes(pin, p)
    run_java("lab", pin, pout)
    ref = read_planes(pout)
    got = p.copy()
    lab.rgb_to_lab_inplace(got)
    assert np.array_equal(ref.p0, got.p0)
    assert np.array_equal(ref.p1, got.p1)
    assert np.array_equal(ref.p2, got.p2)


def test_lab_to_rgb_close(tmp_path: Path) -> None:
    p = random_planes(20, 24, 11)
    pin = tmp_path / "in.bin"
    pout = tmp_path / "out.bin"
    write_planes(pin, p)
    run_java("lab_rgb", pin, pout)
    ref = read_planes(pout)
    got = p.copy()
    lab.rgb_to_lab_inplace(got)
    lab.lab_to_rgb_inplace(got)
    for c in range(3):
        assert np.abs(ref.plane(c).astype(int) - got.plane(c).astype(int)).max() <= 1


def test_fusion_close(tmp_path: Path) -> None:
    orig = random_planes(20, 24, 12)
    gan_in = random_planes(20, 24, 13)
    oin, gin, oout = tmp_path / "o.bin", tmp_path / "g.bin", tmp_path / "r.bin"
    write_planes(oin, orig)
    write_planes(gin, gan_in)
    run_java("fusion", oin, gin, oout)
    ref = read_planes(oout)
    got = fusion.fuse(orig.copy(), gan_in.copy())
    for c in range(3):
        diff = np.abs(ref.plane(c).astype(int) - got.plane(c).astype(int))
        assert diff.mean() <= 0.5
        assert diff.max() <= 4


@pytest.mark.parametrize(
    "filt,name",
    [(Filter.BILINEAR, 0), (Filter.BICUBIC, 1), (Filter.LANCZOS, 2)],
)
def test_resample_exact(tmp_path: Path, filt: Filter, name: int) -> None:
    p = random_planes(17, 23, 14)
    pin, pout = tmp_path / "in.bin", tmp_path / "out.bin"
    write_planes(pin, p)
    run_java("resample", pin, pout, 31, 12, name)
    ref = read_planes(pout)
    got = resize_planes(p, 31, 12, filt)
    assert np.array_equal(ref.p0, got.p0), name
    assert np.array_equal(ref.p1, got.p1), name
    assert np.array_equal(ref.p2, got.p2), name


def test_gaussian_close(tmp_path: Path) -> None:
    f = random_frame(1, 18, 22, 15)
    fin, fout = tmp_path / "in.bin", tmp_path / "out.bin"
    write_frame(fin, f)
    run_java("gaussian", fin, fout, 2.0)
    ref = read_frame(fout)
    got = Frame(gaussian.blur(f.data[0], 2.0)[None, ...])
    assert np.allclose(ref.data, got.data, atol=2e-5)


def test_kernel_close(tmp_path: Path) -> None:
    kout = tmp_path / "k.bin"
    run_java("kernel", kout, 5, 2.0)
    ref = read_kernel(kout)
    got = legendary.kernel(5, 2.0).data
    assert np.allclose(ref, got, atol=1e-6)


@pytest.mark.parametrize(
    "cubic,align", [(False, False), (True, False), (False, True), (True, True)]
)
def test_frame_resize_close(tmp_path: Path, cubic: bool, align: bool) -> None:
    f = random_frame(3, 17, 21, 16)
    fin, fout = tmp_path / "in.bin", tmp_path / "out.bin"
    write_frame(fin, f)
    run_java("frame_resize", fin, fout, 9, 13, str(cubic).lower(), str(align).lower())
    ref = read_frame(fout)
    got = legendary.resize_frame(f, 9, 13, cubic, align)
    assert np.allclose(ref.data, got.data, atol=2e-5)


def test_area_close(tmp_path: Path) -> None:
    f = random_frame(3, 20, 24, 17)
    fin, fout = tmp_path / "in.bin", tmp_path / "out.bin"
    write_frame(fin, f)
    run_java("area", fin, fout, 7, 9)
    ref = read_frame(fout)
    got = legendary.area_frame(f, 7, 9)
    assert np.allclose(ref.data, got.data, atol=2e-5)


def test_normalize_close(tmp_path: Path) -> None:
    f = random_frame(1, 16, 16, 18)
    fin, fout = tmp_path / "in.bin", tmp_path / "out.bin"
    write_frame(fin, f)
    run_java("normalize", fin, fout)
    ref = read_frame(fout)
    got = legendary.normalize(f)
    assert np.allclose(ref.data, got.data, atol=1e-6)


def test_focus_scalar(tmp_path: Path) -> None:
    yy, xx = np.mgrid[0:32, 0:32].astype(np.float32)
    f = Frame(((xx + yy) / 62.0)[None, :, :])
    fin, fout = tmp_path / "in.bin", tmp_path / "out.bin"
    write_frame(fin, f)
    run_java("focus", fin, fout, 0.5, 0.5)
    ref = struct.unpack(">f", fout.read_bytes())[0]
    got = legendary.focus(f, (0.5, 0.5))
    assert got is not None
    assert abs(ref - got) < 1e-6


@pytest.mark.parametrize("orientation", list(range(2, 9)))
def test_exif_transpose_exact(tmp_path: Path, orientation: int) -> None:
    p = random_planes(7, 10, 19)
    pin, pout = tmp_path / "in.bin", tmp_path / "out.bin"
    write_planes(pin, p)
    run_java("exif", pin, pout, orientation)
    ref = read_planes(pout)
    got = p.exif_transposed(orientation)
    assert (ref.width, ref.height) == (got.width, got.height)
    assert np.array_equal(ref.p0, got.p0)
    assert np.array_equal(ref.p1, got.p1)
    assert np.array_equal(ref.p2, got.p2)


def test_split_close(tmp_path: Path) -> None:
    p = random_planes(16, 16, 20)
    pin = tmp_path / "in.bin"
    base_out = tmp_path / "base.bin"
    high_out = tmp_path / "high.bin"
    write_planes(pin, p)
    run_java("split", pin, base_out, high_out)
    ref_base = read_frame(base_out)
    ref_high = read_frame(high_out)
    got_base, got_high = legendary.split_planes(p)
    assert np.allclose(ref_base.data, got_base.data, atol=2e-5)
    assert np.allclose(ref_high.data, got_high.data, atol=2e-5)
