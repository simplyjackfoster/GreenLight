#!/usr/bin/env python3
"""Evaluation suite for full green-chime pipeline.

Input CSV schema (required columns):
- frame_index: int
- gt_state: red|green|yellow|off
- pred_state: red|green|yellow|off|none
- chime: 0|1
- lighting: day|night|dusk
- visible_lights: int

Metrics:
- True positive chimes
- False positive chimes
- False negatives (missed red->green transitions)
- Median + P95 chime latency (frames from transition to first chime)
- False positives per hour
- Breakdown by day/night and single/multiple lights
- Trust gate verdict (UNSHIPPABLE / TARGET / NEEDS_WORK)
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median


TARGET_FP_PER_HOUR = 0.5
UNSHIPPABLE_FP_PER_HOUR = 1.0
TARGET_TRUE_POSITIVE_RATE = 0.92


@dataclass(frozen=True)
class FrameRow:
    frame_index: int
    gt_state: str
    pred_state: str
    chime: bool
    lighting: str
    visible_lights: int


@dataclass(frozen=True)
class BreakdownMetrics:
    tp_chimes: int
    fp_chimes: int
    fn_transitions: int
    false_positives_per_hour: float


@dataclass(frozen=True)
class EvalMetrics:
    total_frames: int
    total_duration_hours: float

    true_positive_chimes: int
    false_positive_chimes: int
    false_negatives: int

    true_positive_rate: float
    false_positives_per_hour: float

    median_latency_frames: float
    p95_latency_frames: float

    day_breakdown: BreakdownMetrics
    night_breakdown: BreakdownMetrics
    single_light_breakdown: BreakdownMetrics
    multiple_lights_breakdown: BreakdownMetrics

    trust_verdict: str


@dataclass(frozen=True)
class Event:
    transition_frame: int
    chime_frame: int | None


def parse_bool(raw: str) -> bool:
    value = raw.strip().lower()
    return value in {"1", "true", "yes", "y"}


def load_rows(path: Path) -> list[FrameRow]:
    rows: list[FrameRow] = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"frame_index", "gt_state", "pred_state", "chime", "lighting", "visible_lights"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"Missing required columns: {sorted(missing)}")

        for r in reader:
            rows.append(
                FrameRow(
                    frame_index=int(r["frame_index"]),
                    gt_state=r["gt_state"].strip().lower(),
                    pred_state=r["pred_state"].strip().lower(),
                    chime=parse_bool(r["chime"]),
                    lighting=r["lighting"].strip().lower(),
                    visible_lights=int(r["visible_lights"]),
                )
            )

    rows.sort(key=lambda x: x.frame_index)
    return rows


def detect_gt_transitions(rows: list[FrameRow]) -> list[int]:
    transitions: list[int] = []
    if not rows:
        return transitions

    prev = rows[0].gt_state
    for row in rows[1:]:
        if prev == "red" and row.gt_state == "green":
            transitions.append(row.frame_index)
        prev = row.gt_state
    return transitions


def match_chimes(rows: list[FrameRow], transitions: list[int], max_latency_frames: int) -> tuple[list[Event], list[int]]:
    chime_frames = [r.frame_index for r in rows if r.chime]
    used_chimes: set[int] = set()
    events: list[Event] = []

    for t in transitions:
        chosen: int | None = None
        for cf in chime_frames:
            if cf in used_chimes:
                continue
            if cf < t:
                continue
            if cf - t > max_latency_frames:
                break
            chosen = cf
            break

        if chosen is not None:
            used_chimes.add(chosen)
        events.append(Event(transition_frame=t, chime_frame=chosen))

    fp_chimes = [cf for cf in chime_frames if cf not in used_chimes]
    return events, fp_chimes


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    values = sorted(values)
    idx = (len(values) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(values) - 1)
    frac = idx - lo
    return values[lo] * (1.0 - frac) + values[hi] * frac


def compute_breakdown(rows: list[FrameRow], fps: float, max_latency_frames: int) -> BreakdownMetrics:
    transitions = detect_gt_transitions(rows)
    events, fp = match_chimes(rows, transitions, max_latency_frames)

    tp = sum(1 for e in events if e.chime_frame is not None)
    fn = sum(1 for e in events if e.chime_frame is None)

    hours = (len(rows) / fps) / 3600.0 if rows else 0.0
    fp_per_hour = (len(fp) / hours) if hours > 0 else 0.0

    return BreakdownMetrics(
        tp_chimes=tp,
        fp_chimes=len(fp),
        fn_transitions=fn,
        false_positives_per_hour=fp_per_hour,
    )


def evaluate(rows: list[FrameRow], fps: float, max_latency_frames: int) -> EvalMetrics:
    transitions = detect_gt_transitions(rows)
    events, fp_chimes = match_chimes(rows, transitions, max_latency_frames)

    tp = sum(1 for e in events if e.chime_frame is not None)
    fn = sum(1 for e in events if e.chime_frame is None)

    latencies = [float(e.chime_frame - e.transition_frame) for e in events if e.chime_frame is not None]

    total_hours = (len(rows) / fps) / 3600.0 if rows else 0.0
    fp_per_hour = (len(fp_chimes) / total_hours) if total_hours > 0 else 0.0
    tpr = (tp / len(transitions)) if transitions else 0.0

    day_rows = [r for r in rows if r.lighting == "day"]
    night_rows = [r for r in rows if r.lighting == "night"]

    single_rows = [r for r in rows if r.visible_lights <= 1]
    multi_rows = [r for r in rows if r.visible_lights > 1]

    day = compute_breakdown(day_rows, fps, max_latency_frames)
    night = compute_breakdown(night_rows, fps, max_latency_frames)
    single = compute_breakdown(single_rows, fps, max_latency_frames)
    multi = compute_breakdown(multi_rows, fps, max_latency_frames)

    if fp_per_hour > UNSHIPPABLE_FP_PER_HOUR:
        verdict = "UNSHIPPABLE"
    elif fp_per_hour < TARGET_FP_PER_HOUR and tpr > TARGET_TRUE_POSITIVE_RATE:
        verdict = "TARGET"
    else:
        verdict = "NEEDS_WORK"

    return EvalMetrics(
        total_frames=len(rows),
        total_duration_hours=total_hours,
        true_positive_chimes=tp,
        false_positive_chimes=len(fp_chimes),
        false_negatives=fn,
        true_positive_rate=tpr,
        false_positives_per_hour=fp_per_hour,
        median_latency_frames=median(latencies) if latencies else 0.0,
        p95_latency_frames=percentile(latencies, 0.95),
        day_breakdown=day,
        night_breakdown=night,
        single_light_breakdown=single,
        multiple_lights_breakdown=multi,
        trust_verdict=verdict,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate full chime pipeline metrics")
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--max-latency-frames", type=int, default=120)
    parser.add_argument("--out-json", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_rows(args.input_csv)
    metrics = evaluate(rows, fps=args.fps, max_latency_frames=args.max_latency_frames)

    payload = asdict(metrics)
    serialized = json.dumps(payload, indent=2)
    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
