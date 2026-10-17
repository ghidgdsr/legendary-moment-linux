from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image, ImageOps

from .types import Planes

try:  # optional HEIC/HEIF support
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover
    pass

MAX_IMAGE_PIXELS = 50_000_000


def decode_image(data: bytes, max_pixels: int = MAX_IMAGE_PIXELS) -> Planes:
    img = Image.open(BytesIO(data))
    if img.width * img.height > max_pixels:
        raise ValueError("照片尺寸过大")
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    rgb = np.asarray(img)
    return Planes.from_rgb(np.ascontiguousarray(rgb))


def encode_png(planes: Planes) -> bytes:
    buf = BytesIO()
    Image.fromarray(planes.to_rgb(), mode="RGB").save(buf, format="PNG")
    return buf.getvalue()


def encode_jpeg(planes: Planes, quality: int = 92) -> bytes:
    buf = BytesIO()
    Image.fromarray(planes.to_rgb(), mode="RGB").save(
        buf, format="JPEG", quality=quality, subsampling=0
    )
    return buf.getvalue()


def make_original_preview(
    data: bytes, max_side: int = 2048, quality: int = 90
) -> tuple[bytes, int, int]:
    """Decode/validate an upload and return a browser-friendly JPEG preview.

    Returns (jpeg_bytes, oriented_width, oriented_height).
    """
    img = Image.open(BytesIO(data))
    if img.width * img.height > MAX_IMAGE_PIXELS:
        raise ValueError("照片尺寸过大")
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    width, height = img.size
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, subsampling=0)
    return buf.getvalue(), width, height


def preview_png(planes: Planes, max_side: int = 1280) -> bytes:
    from .sizes import preview_size

    pw, ph = preview_size(planes.width, planes.height, max_side)
    if pw != planes.width or ph != planes.height:
        from .resample import Filter, resize_planes

        planes = resize_planes(planes, pw, ph, Filter.BILINEAR)
    return encode_png(planes)
