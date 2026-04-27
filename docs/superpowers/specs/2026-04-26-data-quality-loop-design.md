# Data Quality Loop — Design Spec
**Date:** 2026-04-26
**File:** `dataset_pipeline.py`
**Approach:** Option B — new pipeline stage within the existing file

---

## Goal

Implement the Data Quality Loop described in ARCHITECTURE.md:
- Hard-negative mining (tail lights, reflections, LED signs, lens flare)
- Per-record tagging by lighting condition (day / dusk / night)
- Per-record tagging by light scale (near / medium / distant)
- Stratum-balanced output before the stratified split

This runs entirely within `dataset_pipeline.py` after all three parsers complete and before `split_stratified`.

---

## Data Model

`AnnotationRecord` gains two optional fields:

```python
@dataclass(frozen=True)
class AnnotationRecord:
    dataset: str
    image_path: Path
    bbox_xyxy: tuple[float, float, float, float]
    label: str
    raw_label: str
    lighting: str | None = None   # "day" | "dusk" | "night"
    scale: str | None = None      # "near" | "medium" | "distant"
```

`TARGET_CLASSES` expands from 4 to 5:
```python
TARGET_CLASSES = ("red", "green", "yellow", "off", "hard_negative")
```

Hard negatives are full `AnnotationRecord` instances with `label="hard_negative"` and `raw_label="mined"`. They are sourced from the same images already parsed — no new datasets required.

**Rationale for 5th class:** `off` means "light present but dark." `hard_negative` means "not a traffic light at all." Keeping them separate gives the fusion engine an explicit high-confidence suppression signal and keeps `off` semantically pure.

---

## Pipeline Stage: `run_data_quality_loop`

Called in `main()` after all parsers complete, before `split_stratified`. Skipped entirely when `--skip-quality-loop` is passed.

```
all_records (parsed)
    → Step 1: tag lighting + scale
    → Step 2: mine hard negatives
    → Step 3: balance strata
    → balanced_records (to split_stratified)
```

### Step 1 — Tag each record

For each record, load the cropped bbox region and compute:

**Lighting tag** — mean luminance of the crop:
- `< 85` → `"night"`
- `85–170` → `"dusk"`
- `> 170` → `"day"`

Thresholds are module-level constants (`LIGHTING_NIGHT_MAX`, `LIGHTING_DAY_MIN`) so they can be tuned without touching logic.

If the image cannot be loaded or the crop is degenerate, `lighting` and `scale` remain `None`. The record is kept and participates in the split; it is excluded from stratum balancing only.

**Scale tag** — bbox area as a fraction of image area:
- `< 0.01` (< 1%) → `"distant"`
- `0.01–0.05` (1–5%) → `"medium"`
- `> 0.05` (> 5%) → `"near"`

Thresholds are module-level constants (`SCALE_DISTANT_MAX`, `SCALE_NEAR_MIN`).

### Step 2 — Mine hard negatives

For each image that has at least one ground-truth box:
1. Attempt to sample 1–2 random candidate crops from the image.
2. Each candidate crop is sized randomly between 0.5× and 2× the area of a random ground-truth box in the same image, placed at a random position.
3. A candidate is accepted only if its IoU with every ground-truth box in the image is `< 0.1`.
4. Accepted crops are added as `AnnotationRecord` with `label="hard_negative"`, `raw_label="mined"`, and the same `lighting`/`scale` tags computed via the same luminance/area logic.

**Cap:** Total hard negatives are capped at 20% of the non-negative record count. Mining stops early once the cap is reached. This prevents hard negatives from dominating the dataset.

If an image cannot be loaded during mining, it is skipped silently (warning logged).

### Step 3 — Balance strata

Strata are defined as `(lighting, scale, label)` tuples. Records with `lighting=None` or `scale=None` are excluded from balancing but retained in the output.

1. Find the rarest stratum count `R` across all `(lighting, scale, label)` combinations.
2. Compute the cap per stratum: `floor(R × balance_cap_multiplier)`. Default multiplier is `2.0`, so the cap is at most 2× the rarest stratum.
3. Undersample each stratum that exceeds the cap by random selection (seeded).
4. Records excluded from balancing (untagged) are always kept in full.

Residual class imbalance after stratum balancing is handled downstream by `WeightedRandomSampler` weights, which are already computed and written to the manifest.

---

## New CLI Arguments

| Argument | Default | Description |
|---|---|---|
| `--skip-quality-loop` | off | Skip all three quality loop steps; preserves exact current behavior |
| `--balance-cap` | `2.0` | Max stratum size as a multiple of the rarest stratum |
| `--hard-neg-ratio` | `0.20` | Max hard negatives as a fraction of non-negative record count |
| `--hard-neg-per-image` | `2` | Max hard negative candidates sampled per image |

---

## Error Handling

| Condition | Behavior |
|---|---|
| Image unreadable during tagging | `lighting=None`, `scale=None`; record kept; warning logged |
| Image unreadable during mining | Image skipped; warning logged |
| Zero hard negatives mined | Warning logged; pipeline continues |
| All records untagged | Balancing step no-ops; warning logged |
| `--skip-quality-loop` | Steps 1–3 bypassed entirely; `all_records` passed directly to split |

---

## Testing

New unit tests in `Tests/test_dataset_pipeline.py` (new file):

- Luminance thresholds: synthetic crops at known mean values hit correct bins
- Scale thresholds: bbox fractions at boundary values produce correct bins
- IoU check: candidate crop overlapping a ground-truth box is rejected; non-overlapping is accepted
- Balance cap: given a known stratum distribution, output counts respect the cap multiplier
- `--skip-quality-loop`: records pass through unmodified with no `lighting`/`scale` fields set

No integration test — full dataset required on disk.

---

## Files Changed

| File | Change |
|---|---|
| `dataset_pipeline.py` | Add `lighting`/`scale` fields to `AnnotationRecord`; expand `TARGET_CLASSES`; add `run_data_quality_loop` and helpers; add CLI args; call from `main()` |
| `Tests/test_dataset_pipeline.py` | New file with unit tests for quality loop logic |

`ARCHITECTURE.md` is already up to date — no changes needed.
