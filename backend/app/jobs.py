from __future__ import annotations

import queue
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..leica_core.engine import LeicaEngine, ProcessOptions, ProcessResult
from ..leica_core.sizes import BokehOutput, ProcessingMode

PROGRESS = {
    "read": 0.05,
    "depth": 0.18,
    "color": 0.30,
    "fuse": 0.45,
    "color_skip": 0.30,
    "fuse_skip": 0.45,
    "render_prep": 0.55,
    "render_model": 0.72,
    "highlight": 0.86,
    "color_convert": 0.91,
    "encode": 0.97,
}


@dataclass
class Job:
    id: str
    directory: Path
    original_name: str
    options: ProcessOptions
    status: str = "queued"
    stage: str = "queued"
    message: str = "排队中"
    progress: float = 0.0
    error: str | None = None
    width: int | None = None
    height: int | None = None
    focus: float | None = None
    rendered: bool = False
    downscaled: bool = False
    reason: str = ""
    timings: dict[str, float] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def result_path(self) -> Path:
        return self.directory / "result.png"

    @property
    def original_path(self) -> Path:
        return self.directory / "original.jpg"

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "progress": round(self.progress, 3),
            "error": self.error,
            "width": self.width,
            "height": self.height,
            "focus": self.focus,
            "rendered": self.rendered,
            "downscaled": self.downscaled,
            "reason": self.reason,
            "timings": {k: round(v, 3) for k, v in self.timings.items()},
            "mode": self.options.mode.name,
            "aperture": self.options.aperture,
            "output_size": self.options.output_size.name,
            "original_url": f"/api/jobs/{self.id}/original",
            "result_url": (
                f"/api/jobs/{self.id}/result" if self.status == "done" else None
            ),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class QueueFullError(RuntimeError):
    pass


class JobManager:
    def __init__(
        self,
        data_dir: Path,
        max_queue: int = 3,
        ttl_seconds: int = 3600,
        threads: int | None = None,
        model_dir: str | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self.max_queue = max_queue
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._queue: queue.Queue[tuple[Job, bytes] | None] = queue.Queue(
            maxsize=max_queue
        )
        self._stop = threading.Event()
        self._engine = LeicaEngine(model_dir=model_dir, threads=threads)
        self._worker = threading.Thread(
            target=self._work, name="leica-worker", daemon=True
        )
        self._cleaner = threading.Thread(
            target=self._clean, name="leica-cleaner", daemon=True
        )

    def start(self) -> None:
        if self._worker.is_alive():
            return
        self._stop.clear()
        # A previous stop() consumed the sentinel; always start with a clean queue.
        self._queue = queue.Queue(maxsize=self.max_queue)
        self._worker = threading.Thread(
            target=self._work, name="leica-worker", daemon=True
        )
        self._cleaner = threading.Thread(
            target=self._clean, name="leica-cleaner", daemon=True
        )
        self._worker.start()
        self._cleaner.start()

    def stop(self) -> None:
        if not self._worker.is_alive():
            return
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._worker.join(timeout=5)
        self._cleaner.join(timeout=5)
        self._engine.close()

    # ------------------------------------------------------------------
    def create_job(self, original_name: str, options: ProcessOptions) -> Job:
        job_id = uuid.uuid4().hex
        directory = self.data_dir / job_id
        directory.mkdir(parents=True, exist_ok=False)
        job = Job(
            id=job_id,
            directory=directory,
            original_name=original_name,
            options=options,
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def submit(self, job: Job, payload: bytes) -> None:
        try:
            self._queue.put_nowait((job, payload))
        except queue.Full:
            self._remove(job.id)
            raise QueueFullError("处理队列已满，请稍后重试")

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def queue_depth(self) -> int:
        return self._queue.qsize()

    # ------------------------------------------------------------------
    def _update(self, job: Job, **fields: Any) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(job, key, value)
            job.updated_at = time.time()

    def _work(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            job, payload = item
            self._update(
                job,
                status="processing",
                stage="read",
                message="开始处理",
                progress=0.02,
                error=None,
            )

            def progress(stage: str, message: str) -> None:
                self._update(
                    job,
                    stage=stage,
                    message=message,
                    progress=PROGRESS.get(stage, job.progress),
                )

            try:
                result: ProcessResult = self._engine.process_bytes(
                    payload, job.options, progress
                )
                job.result_path.write_bytes(result.image)
                self._update(
                    job,
                    status="done",
                    stage="done",
                    message="处理完成",
                    progress=1.0,
                    width=result.width,
                    height=result.height,
                    focus=result.focus,
                    rendered=result.rendered,
                    downscaled=result.downscaled,
                    reason=result.reason,
                    timings=result.timings,
                )
            except Exception as exc:  # noqa: BLE001
                self._update(
                    job,
                    status="error",
                    stage="error",
                    message="处理失败",
                    progress=1.0,
                    error=str(exc) or exc.__class__.__name__,
                )
            finally:
                self._queue.task_done()

    def _clean(self) -> None:
        while not self._stop.wait(60.0):
            now = time.time()
            expired: list[str] = []
            with self._lock:
                for job_id, job in self._jobs.items():
                    if job.status in ("done", "error") and now - job.updated_at > self.ttl_seconds:
                        expired.append(job_id)
            for job_id in expired:
                self._remove(job_id)

    def _remove(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job is not None:
            shutil.rmtree(job.directory, ignore_errors=True)
