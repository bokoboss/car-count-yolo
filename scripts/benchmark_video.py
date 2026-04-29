"""Manual benchmark for vehicle_counter tracking.

Example:
    python scripts/benchmark_video.py path\to\video.mp4 --mode people --line 100,300,900,300
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from PyQt6.QtCore import QPoint  # noqa: E402

from vehicle_counter import config  # noqa: E402
from vehicle_counter.sources import resolve_local_file_source  # noqa: E402
from vehicle_counter.tracking import track_vehicles  # noqa: E402


def parse_line(value):
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("Line must be x1,y1,x2,y2")
    try:
        x1, y1, x2, y2 = [int(part) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Line coordinates must be integers") from exc
    return QPoint(x1, y1), QPoint(x2, y2)


def build_parser():
    parser = argparse.ArgumentParser(description="Benchmark YOLO counting on a local video.")
    parser.add_argument("video", help="Path to a local video file")
    parser.add_argument(
        "--line",
        type=parse_line,
        required=True,
        help="Counting line as x1,y1,x2,y2 in source video pixels",
    )
    parser.add_argument(
        "--mode",
        choices=(config.COUNTING_MODE_VEHICLE, config.COUNTING_MODE_PEOPLE),
        default=config.COUNTING_MODE_VEHICLE,
    )
    parser.add_argument("--model-size", choices=config.MODEL_SIZE_OPTIONS, default="small")
    parser.add_argument("--confidence", type=float, default=config.DEFAULT_CONFIDENCE_THRESHOLD)
    parser.add_argument("--frame-skip", type=int, default=config.DEFAULT_FRAME_SKIP)
    parser.add_argument("--imgsz", type=int, default=config.DEFAULT_IMAGE_SIZE)
    parser.add_argument("--device", default=config.DEFAULT_DEVICE)
    parser.add_argument("--half", action="store_true")
    parser.add_argument(
        "--raw-preview",
        action="store_true",
        help="Skip preview box rendering for a cleaner processing benchmark.",
    )
    return parser


def main():
    args = build_parser().parse_args()
    source, error_message = resolve_local_file_source(args.video)
    if error_message:
        raise SystemExit(error_message)

    enabled_classes = config.get_default_enabled_classes_for_mode(args.mode)
    settings = {
        "counting_mode": args.mode,
        "confidence_threshold": args.confidence,
        "frame_skip": args.frame_skip,
        "model_size": args.model_size,
        "enabled_classes": enabled_classes,
        "prioritize_low_latency_live_streams": False,
        "imgsz": args.imgsz,
        "device": args.device,
        "half": args.half,
        "preview_render_mode": (
            config.PREVIEW_RENDER_RAW
            if args.raw_preview
            else config.PREVIEW_RENDER_ANNOTATED
        ),
    }

    started_at = time.perf_counter()
    latest_frame, results, status = track_vehicles(
        video_source=source,
        line_points={"line_1": args.line},
        settings=settings,
        track_label_mode="off",
    )
    elapsed = time.perf_counter() - started_at

    processed_frames = int((results or {}).get("processed_frames", 0))
    fps = processed_frames / elapsed if elapsed else 0.0
    print(f"status={status.get('code') if isinstance(status, dict) else status}")
    if isinstance(status, dict) and status.get("message"):
        print(f"message={status['message']}")
    print(f"elapsed_seconds={elapsed:.3f}")
    print(f"processed_frames={processed_frames}")
    print(f"processing_fps={fps:.2f}")
    print(f"total_count={(results or {}).get('total', 0)}")
    print(f"counts_by_class={(results or {}).get('counts', {})}")
    print(f"latest_frame_available={latest_frame is not None}")


if __name__ == "__main__":
    main()
