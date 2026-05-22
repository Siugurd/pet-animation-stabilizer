# Animation Stability Rules

## Goal

Make a Codex pet feel stable in motion without flattening its personality. The target is not identical frames; the target is coherent body scale, grounded baseline, and believable state-specific movement.

Default to post-hatch optimization. Keep the original hatch result intact and build a separate candidate so the user can compare before and after contact sheets and videos.

## Best Re-Entry Point

When a full hatch-pet run is available, re-enter from:

```text
run/decoded/<state>.png
```

This is after visual generation and provenance recording, but before the old per-frame `fit_to_cell()` decision permanently placed each sprite into a `192x208` cell.

If `decoded/` is unavailable, use `run/frames/`. If only a packaged `spritesheet.webp` is available, split the atlas and treat the result as a post-cell repair with reduced ability to recover original vertical motion.

## What To Preserve

- Character identity: face, palette, silhouette, markings, prop design, and outline weight.
- Motion intent: waving should wave, jumping should jump, failed should react, review should focus.
- Local motion: hands, paws, ears, facial expression, props, and small body bob may move.

## What To Stabilize

- Body scale within each row.
- Foot or body baseline for standing-like rows.
- Subject core center for rows where limbs or props extend outward.
- Jumping takeoff and landing line.
- Frame rhythm when one frame is visibly too large, too small, or off-beat.

## Row-Level Scale

Use a single scale for the whole row when any frame exceeds the safe cell bounds. This avoids frame-to-frame size popping.

Recommended cell contract:

```text
cell: 192x208
content max: 182x198
nominal safety margin: 5px on each side
```

Compute the scale from the largest subject width/height in the row, then apply it to every frame:

```text
row_scale = min(182 / max_width, 198 / max_height, 1.0)
```

Do not enlarge small frames by default. Enlarging often blurs pixel-adjacent art and can hide true generation problems.

## Subject Anchor

Avoid aligning the full bbox center when limbs, props, tails, or ears move. Full-bbox centering lets the moving extremity drag the body in the opposite direction.

Prefer a subject anchor:

```text
x anchor: subject core center, usually near cell center
y anchor: baseline or bottom anchor depending on state
```

If subject-core detection is unavailable, use the alpha bbox as a conservative fallback, then verify visually.

## Baseline

For non-jumping rows, keep the bottom of the subject near a fixed baseline. This removes floating and vertical jitter.

Good candidates:

- The median `bbox.bottom` of stable frames.
- A fixed row baseline around `200-203px` when the pet is meant to stand near the bottom of a `208px` cell.
- The idle row's stable bottom if it is a good reference pose.

Use baseline alignment for:

```text
idle, waving, waiting, running, review
```

Use with judgment for:

```text
running-right, running-left, failed
```

## Jumping

Do not center `jumping` frames independently. That destroys the meaning of the jump.

Use this rule:

```text
crouch / takeoff / landing frames: bottom aligns to baseline
airborne frames: bottom rises above baseline
```

The frame may become shorter during crouch, but the feet or lowest grounded point should not float before takeoff.

## Area And Rhythm

Use non-transparent pixel area as a signal, not as the only truth.

Flag frames that are much smaller or larger than the row median. Common repairs:

- Scale down an over-expanded limb or body frame.
- Move a frame back to baseline.
- Replace a single rhythm-breaking frame with a nearby stable frame.
- Regenerate the row if identity, body type, or silhouette changed.

## Acceptance

A stabilized row is acceptable when:

- The pet reads as the same character across the row.
- Body size feels consistent at playback speed.
- Non-jumping rows do not drift vertically.
- Moving limbs or props do not pull the body around the cell.
- Jumping has a clear grounded start, airborne phase, and landing.

An optimized candidate is acceptable when the user can inspect:

- The original spritesheet or contact sheet.
- The optimized spritesheet and contact sheet.
- Original and optimized videos when available.
- A stability report listing the row-level warnings and paths used.
