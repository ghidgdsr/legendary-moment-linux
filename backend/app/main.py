from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..leica_core.imageio import MAX_IMAGE_PIXELS, make_original_preview
from ..leica_core.sizes import BokehOutput, ProcessingMode
from .auth import Auth
from .jobs import JobManager, QueueFullError

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
DATA_DIR = Path(os.environ.get("LEICA_DATA_DIR", ROOT / "data" / "jobs"))
TOKEN_FILE = Path(os.environ.get("LEICA_TOKEN_FILE", ROOT / "data" / "token.txt"))

MAX_UPLOAD_MB = int(os.environ.get("LEICA_MAX_UPLOAD_MB", "30"))
MAX_QUEUE = int(os.environ.get("LEICA_MAX_QUEUE", "3"))
TTL_SECONDS = int(os.environ.get("LEICA_JOB_TTL", "3600"))
MAX_PIXELS = int(os.environ.get("LEICA_MAX_PIXELS", str(MAX_IMAGE_PIXELS)))

def load_or_create_token(path: Path) -> tuple[str, bool]:
    """Read the token from path; only create a new one if missing/empty.

    The file is the single source of truth: an existing token is never rotated
    on restart. Returns (token, created).
    """
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise RuntimeError(f"无法读取令牌文件: {path}") from exc
        for line in text.splitlines():
            token = line.strip()
            if token:
                try:
                    path.chmod(0o600)
                except OSError:
                    pass
                return token, False

    token = secrets.token_urlsafe(18)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token, True


TOKEN, TOKEN_CREATED = load_or_create_token(TOKEN_FILE)

AUTH = Auth(TOKEN, os.environ.get("LEICA_ALLOW_CIDRS"))
MANAGER = JobManager(
    DATA_DIR,
    max_queue=MAX_QUEUE,
    ttl_seconds=TTL_SECONDS,
    threads=int(os.environ["LEICA_ORT_THREADS"])
    if os.environ.get("LEICA_ORT_THREADS")
    else None,
    model_dir=os.environ.get("LEICA_MODEL_DIR"),
)


def require_auth(request: Request) -> None:
    AUTH.check(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    MANAGER.start()
    port = os.environ.get("LEICA_PORT", "8000")
    print("=" * 62, flush=True)
    print("传奇一瞬 Linux Web 已启动", flush=True)
    print(f"本机访问: http://127.0.0.1:{port}", flush=True)
    print("局域网访问: http://<本机局域网IP>:" + str(port), flush=True)
    print(f"访问令牌: {TOKEN}", flush=True)
    print(
        f"令牌文件: {TOKEN_FILE}（{'已生成' if TOKEN_CREATED else '已存在，保持不变'}）",
        flush=True,
    )
    print("=" * 62, flush=True)
    try:
        yield
    finally:
        MANAGER.stop()


app = FastAPI(title="传奇一瞬 Linux 移植", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    models = ROOT / "vendor" / "models"
    names = [
        "legendary-1.0-depth.fp16.onnx",
        "legendary-1.0-arnet.fp16.onnx",
        "legendary-1.0-gan.fp16.onnx",
    ]
    return {
        "status": "ok",
        "models": all((models / n).is_file() for n in names),
        "queue": MANAGER.queue_depth(),
    }


@app.get("/api/config")
def config() -> dict:
    return {
        "modes": [
            {
                "name": m.name,
                "label": m.label,
                "color": m.color_enabled,
                "blur": m.blur_enabled,
            }
            for m in ProcessingMode
        ],
        "apertures": [
            {"value": v, "label": f"f/{v:g}"}
            for v in [0.95, 1.8, 2.0, 2.8, 4.0, 5.6]
        ],
        "output_sizes": [
            {"name": "SIZE_2048", "label": "2048", "long_edge": 2048},
            {"name": "SIZE_1024", "label": "1024", "long_edge": 1024},
            {"name": "ORIGINAL", "label": "原图直出", "long_edge": None},
        ],
        "defaults": {
            "mode": "COLOR_AND_BLUR",
            "aperture": 2.0,
            "output_size": "SIZE_2048",
        },
        "limits": {
            "max_upload_mb": MAX_UPLOAD_MB,
            "max_pixels": MAX_PIXELS,
            "queue": MAX_QUEUE,
            "ttl_seconds": TTL_SECONDS,
        },
        "token_required": True,
    }


@app.post("/api/jobs")
async def create_job(
    _: None = Depends(require_auth),
    file: UploadFile = File(...),
    mode: str = Form(...),
    aperture: float = Form(2.0),
    focus_x: float | None = Form(None),
    focus_y: float | None = Form(None),
    output_size: str = Form("SIZE_2048"),
) -> dict:
    try:
        processing_mode = ProcessingMode[mode]
    except KeyError as exc:
        raise HTTPException(status_code=422, detail="未知的处理模式") from exc
    try:
        out_size = BokehOutput[output_size]
    except KeyError as exc:
        raise HTTPException(status_code=422, detail="未知的输出尺寸") from exc

    from ..leica_core.legendary import APERTURES, gain

    if not any(abs(aperture - float(v)) < 1e-9 for v in APERTURES):
        raise HTTPException(status_code=422, detail="不支持的光圈")
    try:
        gain(float(aperture))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    focus: tuple[float, float] | None = None
    if focus_x is not None and focus_y is not None:
        focus = (
            min(max(float(focus_x), 0.0), 1.0),
            min(max(float(focus_y), 0.0), 1.0),
        )
    if processing_mode.blur_enabled and focus is None:
        raise HTTPException(status_code=422, detail="请先在原照片上点击焦点")

    limit = MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status_code=413, detail=f"文件超过 {MAX_UPLOAD_MB} MB 限制"
        )
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")

    try:
        preview, width, height = make_original_preview(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"无法解码这张照片: {exc}") from exc
    if width * height > MAX_PIXELS:
        raise HTTPException(status_code=413, detail="照片像素数超过限制")
    if (
        processing_mode.blur_enabled
        and out_size == BokehOutput.ORIGINAL
        and max(width, height) > 2048
    ):
        raise HTTPException(
            status_code=422,
            detail="CPU 版本的原图直出虚化限制长边 2048，请选择 2048 或 1024",
        )

    from ..leica_core.engine import ProcessOptions

    options = ProcessOptions(
        mode=processing_mode,
        aperture=float(aperture),
        focus=focus,
        output_size=out_size,
    )
    job = MANAGER.create_job(file.filename or "upload", options)
    try:
        job.original_path.write_bytes(preview)
    except Exception as exc:  # noqa: BLE001
        MANAGER._remove(job.id)  # noqa: SLF001
        raise HTTPException(status_code=500, detail="无法保存上传预览") from exc

    try:
        MANAGER.submit(job, data)
    except QueueFullError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return job.public()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, _: None = Depends(require_auth)) -> dict:
    job = MANAGER.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return job.public()


@app.get("/api/jobs/{job_id}/result")
def job_result(job_id: str, _: None = Depends(require_auth)) -> FileResponse:
    job = MANAGER.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    if job.status != "done" or not job.result_path.is_file():
        raise HTTPException(status_code=409, detail="结果尚未生成")
    return FileResponse(
        job.result_path,
        media_type="image/png",
        filename=f"传奇一瞬-{job.id[:8]}.png",
    )


@app.get("/api/jobs/{job_id}/original")
def job_original(job_id: str, _: None = Depends(require_auth)) -> FileResponse:
    job = MANAGER.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    if not job.original_path.is_file():
        raise HTTPException(status_code=404, detail="原图预览不存在")
    return FileResponse(job.original_path, media_type="image/jpeg")
