#!/usr/bin/env python3
"""Video annotation tool for traffic-light ground-truth labeling."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

try:
    import cv2

    CV2_AVAILABLE = True
except ModuleNotFoundError:
    CV2_AVAILABLE = False

KEY_MAP = {
    ord("r"): "red",
    ord("g"): "green",
    ord("y"): "yellow",
    ord("o"): "off",
}


def interpolate_annotations(
    keyframes: dict[int, str],
    total_frames: int,
) -> dict[int, str]:
    if not keyframes:
        raise ValueError("No keyframes provided")

    sorted_keys = sorted(keyframes)
    result: dict[int, str] = {}

    for i, kf in enumerate(sorted_keys):
        state = keyframes[kf]
        end = sorted_keys[i + 1] if i + 1 < len(sorted_keys) else total_frames
        for f in range(kf, end):
            result[f] = state

    first_state = keyframes[sorted_keys[0]]
    for f in range(0, sorted_keys[0]):
        result[f] = first_state

    return result


def build_frame_csv(
    annotations: dict[int, str],
    lighting: str,
    visible_lights: int,
    fps: float,
) -> list[dict[str, str]]:
    _ = fps
    rows = []
    for frame_index in sorted(annotations):
        rows.append(
            {
                "frame_index": str(frame_index),
                "gt_state": annotations[frame_index],
                "pred_state": "none",
                "chime": "0",
                "lighting": lighting,
                "visible_lights": str(visible_lights),
            }
        )
    return rows


def save_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["frame_index", "gt_state", "pred_state", "chime", "lighting", "visible_lights"]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def annotate_interactive(
    video_path: Path,
    output_csv: Path,
    lighting: str,
    visible_lights: int,
) -> None:
    if not CV2_AVAILABLE:
        raise SystemExit("OpenCV not available. Install with: pip install opencv-python")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"Cannot open video: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    keyframes: dict[int, str] = {}
    frame_idx = 0
    paused = True
    current_state = "unknown"

    print(f"Annotating {video_path.name} ({total_frames} frames @ {fps:.1f} fps)")
    print("Controls: r=red g=green y=yellow o=off SPACE=play/pause <-/->=step s=save q=quit")

    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break

        h, w = frame.shape[:2]
        overlay = frame.copy()
        colour = {
            "red": (0, 0, 220),
            "green": (0, 200, 0),
            "yellow": (0, 200, 220),
            "off": (150, 150, 150),
        }.get(current_state, (200, 200, 200))

        cv2.rectangle(overlay, (0, 0), (w, 50), (30, 30, 30), -1)
        cv2.putText(
            overlay,
            f"Frame {frame_idx}/{total_frames - 1} State: {current_state}",
            (10, 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            colour,
            2,
        )
        cv2.putText(
            overlay,
            "r=red g=green y=yellow o=off SPACE=play <-/->=step s=save q=quit",
            (10, h - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (180, 180, 180),
            1,
        )

        cv2.imshow("GreenLight Annotator", overlay)
        wait_ms = 0 if paused else max(1, int(1000 / fps))
        key = cv2.waitKey(wait_ms) & 0xFF

        if key == ord("q"):
            break
        if key == ord("s"):
            if keyframes:
                ann = interpolate_annotations(keyframes, total_frames)
                rows = build_frame_csv(ann, lighting, visible_lights, fps)
                save_csv(rows, output_csv)
                print(f"Saved {len(rows)} rows to {output_csv}")
        elif key in KEY_MAP:
            current_state = KEY_MAP[key]
            keyframes[frame_idx] = current_state
            print(f"frame {frame_idx}: {current_state}")
        elif key == ord(" "):
            paused = not paused
        elif key in (83, ord("d")):
            frame_idx = min(frame_idx + 1, total_frames - 1)
            paused = True
        elif key in (81, ord("a")):
            frame_idx = max(frame_idx - 1, 0)
            paused = True

        if not paused:
            frame_idx = min(frame_idx + 1, total_frames - 1)
            if frame_idx == total_frames - 1:
                paused = True

    cap.release()
    cv2.destroyAllWindows()

    if keyframes:
        ann = interpolate_annotations(keyframes, total_frames)
        rows = build_frame_csv(ann, lighting, visible_lights, fps)
        save_csv(rows, output_csv)
        print(f"Saved {len(rows)} rows to {output_csv}")
    else:
        print("No annotations made; nothing saved.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Annotate driving video clips for evaluate.py")
    parser.add_argument("video", type=Path, help="Path to video file")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output CSV path (default: <video_stem>_annotations.csv)",
    )
    parser.add_argument("--lighting", choices=["day", "dusk", "night"], default="day")
    parser.add_argument("--visible-lights", type=int, default=1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output or args.video.with_name(args.video.stem + "_annotations.csv")
    annotate_interactive(
        video_path=args.video,
        output_csv=output,
        lighting=args.lighting,
        visible_lights=args.visible_lights,
    )


if __name__ == "__main__":
    main()
