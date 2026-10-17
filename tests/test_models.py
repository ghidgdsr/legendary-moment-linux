from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from leica_core.models import MODEL_FILES, ModelManager
from leica_core.types import Frame, Planes

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "vendor" / "models"

pytestmark = pytest.mark.skipif(
    not all((MODEL_DIR / name).is_file() for name in MODEL_FILES.values()),
    reason="models not extracted (run scripts/setup.sh)",
)


@pytest.fixture(scope="module")
def manager() -> ModelManager:
    m = ModelManager(model_dir=MODEL_DIR, threads=2)
    yield m
    m.close()


def test_depth_shape(manager: ModelManager) -> None:
    out = manager.run_depth(Frame(np.zeros((3, 70, 70), np.float32)))
    assert out.data.shape == (1, 70, 70)
    assert np.isfinite(out.data).all()


def test_gan_shape(manager: ModelManager) -> None:
    p = Planes(
        np.full((64, 64), 40, np.uint8),
        np.full((64, 64), 90, np.uint8),
        np.full((64, 64), 160, np.uint8),
    )
    out = manager.run_gan(p)
    assert (out.width, out.height) == (64, 64)


def test_arnet_shape(manager: ModelManager) -> None:
    image = Frame(np.full((3, 64, 64), 0.5, np.float32))
    defocus = Frame(np.zeros((1, 64, 64), np.float32))
    out = manager.run_arnet(image, defocus)
    assert out.data.shape == (3, 64, 64)
    assert np.isfinite(out.data).all()
