#!/usr/bin/env python3
"""Process a single image through the ported pipeline (debug/CLI)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from leica_core.engine import LeicaEngine, ProcessOptions  # noqa: E402
from leica_core.sizes import BokehOutput, ProcessingMode  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="传奇一瞬 Linux 单图处理")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--mode",
        choices=[m.name for m in ProcessingMode],
        default="COLOR_AND_BLUR",
    )
    parser.add_argument("--aperture", type=float, default=2.0)
    parser.add_argument("--focus-x", type=float, default=None)
    parser.add_argument("--focus-y", type=float, default=None)
    parser.add_argument(
        "--output-size",
        choices=[o.name for o in BokehOutput],
        default="SIZE_2048",
    )
    parser.add_argument("--model-dir", type=Path, default=None)
    parser.add_argument("--threads", type=int, default=None)
    args = parser.parse_args()

    mode = ProcessingMode[args.mode]
    focus = None
    if args.focus_x is not None and args.focus_y is not None:
        focus = (args.focus_x, args.focus_y)
    if mode.blur_enabled and focus is None:
        parser.error("虚化模式需要 --focus-x/--focus-y")

    data = args.input.read_bytes()
    engine = LeicaEngine(
        model_dir=str(args.model_dir) if args.model_dir else None,
        threads=args.threads,
    )
    result = engine.process_bytes(
        data,
        ProcessOptions(
            mode=mode,
            aperture=args.aperture,
            focus=focus,
            output_size=BokehOutput[args.output_size],
        ),
        lambda stage, message: print(f"[{stage}] {message}", flush=True),
    )
    engine.close()
    args.output.write_bytes(result.image)
    print(f"wrote {args.output} ({result.width}x{result.height})")
    print(result.reason)
    print(
        "timings: "
        + ", ".join(f"{k}={v:.2f}s" for k, v in result.timings.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
