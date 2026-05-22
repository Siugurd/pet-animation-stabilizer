---
name: pet-animation-stabilizer
description: Non-destructively optimize completed Codex/hatch-pet animations by copying a finished hatch-pet run, re-entering from decoded row strips or extracted frames, rebuilding row-aware 192x208 cells, and producing comparison-ready candidate spritesheets, contact sheets, videos, and reports. Use for completed hatch-pet runs, Codex pet atlases, sprite-to-cell fitting, body scale popping, unstable baselines, jumping takeoff/landing issues, subject drift, or manual pet animation cleanup.
---

# Pet Animation Stabilizer

## Overview

Use this skill after a pet has already been hatched or after hatch-pet has produced visible results the user can compare against. Its purpose is to create a separate optimized candidate, not to replace the original hatch-pet output in place.

The best entry point is a completed hatch-pet run with `decoded/*.png`. From there, re-run the cell-fitting phase with row-aware scale, baseline, anchor, and jumping rules, then continue with hatch-pet's compose, validate, contact sheet, and video tools. This lets users compare the original result against the optimized candidate.

## Default Policy

Do not modify the original hatch-pet run, installed pet, `decoded/`, `imagegen-jobs.json`, or existing package files.

Always write a candidate folder containing:

```text
original/                  # copied original spritesheet/contact sheet/videos when available
extracted-raw-frames/       # frames re-extracted from decoded row strips
frames-stabilized/          # optimized 192x208 frames
final/spritesheet.webp      # optimized candidate atlas
qa/stability-report.json
qa/contact-sheet.png
qa/videos/
qa/candidate-summary.json
```

Only package or overwrite an installed pet after explicit user approval.

## Entry Points

Prefer these sources in order:

1. **Completed hatch-pet run with `decoded/`**: best path. Re-enter from row strips after background removal and before the old frame-to-cell fitting decision.
2. **Completed hatch-pet run with `frames/` only**: acceptable. Optimize existing frames, but original row-strip placement information is partly lost.
3. **Only `spritesheet.webp`**: fallback. Split the atlas into frames and optimize from already-cell-fitted art. This is useful for comparison, but less powerful than starting from `decoded/`.

Do not try to silently hook into a running `hatch-pet` skill. If the user is still hatching a pet, recommend finishing the hatch first, then run this skill on the completed run so there is a visible original to compare with.

## Recommended Workflow

For a completed hatch-pet run:

```bash
python /path/to/pet-animation-stabilizer/scripts/stabilize_pet_frames.py \
  --hatch-run /absolute/path/to/run \
  --candidate-dir /absolute/path/to/run-animation-stabilized
```

The script:

1. Copies original comparison files into `candidate/original/`.
2. Reads `run/decoded/<state>.png` and `run/pet_request.json`.
3. Removes the stored chroma key background.
4. Re-extracts row poses without using per-frame independent centering.
5. Applies row-level scale and state-aware baseline/anchor rules.
6. Writes `candidate/frames-stabilized/`.
7. Uses hatch-pet scripts to compose, validate, make a contact sheet, and render videos.
8. Writes `candidate/qa/candidate-summary.json` with original and optimized paths.

If the run has no `decoded/`, use existing frames:

```bash
python /path/to/pet-animation-stabilizer/scripts/stabilize_pet_frames.py \
  --frames-root /absolute/path/to/run/frames \
  --output-root /absolute/path/to/candidate/frames-stabilized \
  --report /absolute/path/to/candidate/qa/stability-report.json
```

If only an installed pet spritesheet exists:

```bash
python /path/to/pet-animation-stabilizer/scripts/stabilize_pet_frames.py \
  --atlas /absolute/path/to/spritesheet.webp \
  --output-root /absolute/path/to/candidate/frames-stabilized \
  --report /absolute/path/to/candidate/qa/stability-report.json
```

Then recompose with hatch-pet's `compose_atlas.py`.

## Stabilization Strategy

Do not optimize each frame in isolation. Optimize by row and by animation state.

Use one scale per row:

```text
row_scale = min(182 / max_subject_width, 198 / max_subject_height, 1.0)
```

Apply `row_scale` to every frame in the row. This prevents one large action pose from shrinking alone while neighboring poses keep their original size.

Use subject anchors instead of full-frame centering:

```text
x: align the subject body center near the cell center
y: align the baseline or state-specific motion line
```

For standing-like rows, align the subject bottom to a stable baseline. For `jumping`, align takeoff and landing to the baseline while allowing airborne frames to move upward.

## State Guidance

- `idle`: preserve as the visual reference. Use stable scale, stable center, and stable baseline.
- `waving`: lock body center and baseline. Let the hand move; do not let the hand's bbox push the body sideways.
- `waiting`, `running`, `review`: keep body center and baseline stable. Motion should read as local action, not whole-pet drift.
- `running-right`, `running-left`: keep row scale and baseline stable. Allow small rhythmic x changes only when they support locomotion.
- `jumping`: do not vertically center each frame. Keep crouch/takeoff/landing on a shared baseline; let only airborne frames rise.
- `failed`: allow crouching, collapsing, or curling, but avoid sudden scale collapse or bloating unless the animation clearly calls for it.

## User-Facing Prompts

For a completed hatch-pet run:

```text
Use pet-animation-stabilizer on this completed hatch-pet run. Preserve the original files, create a separate candidate folder, re-enter from decoded row strips if available, rebuild optimized frames and spritesheet, and expose original vs optimized contact sheets and videos for comparison.
```

For an installed pet only:

```text
Use pet-animation-stabilizer on this installed spritesheet. Create a separate candidate folder and optimize from the atlas, but tell me that this is a post-cell repair because the original decoded row strips are unavailable.
```

## QA Checklist

Before accepting the optimized candidate, review:

- Original and optimized contact sheets side by side.
- Original and optimized videos at playback speed.
- Row-level scale: no unexpected popping.
- Baseline: non-jumping rows do not float.
- Subject center: body does not slide because a limb or prop moved.
- Jumping: takeoff and landing read as grounded; airborne frames clearly rise.
- Identity: face, palette, silhouette, markings, and prop design remain the same.

## References

Read `references/animation-stability-rules.md` when writing repair notes, evaluating a contact sheet, or proposing changes to hatch-pet's cell-fitting logic.
