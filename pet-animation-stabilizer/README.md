# Pet Animation Stabilizer

`pet-animation-stabilizer` is a Codex skill for improving completed hatch-pet animations.

It preserves the original hatch result, creates a separate candidate version, stabilizes each animation row's scale, subject position, foot baseline, and jumping takeoff/landing points, then outputs the optimized result for easy before-and-after comparison.

## What It Does

- Re-enters from a completed hatch-pet run, preferably from `decoded/*.png`.
- Rebuilds animation frames with row-aware scale and anchor rules.
- Keeps the original hatch-pet output untouched.
- Produces a separate optimized candidate folder.
- Outputs comparison-ready contact sheets, videos, spritesheets, and a stability report.

## Install

Clone this repository into your Codex skills directory:

```bash
git clone https://github.com/<your-username>/pet-animation-stabilizer.git \
  ~/.codex/skills/pet-animation-stabilizer
```

Or copy the folder manually:

```bash
cp -R pet-animation-stabilizer ~/.codex/skills/
```

## Usage

For a completed hatch-pet run:

```bash
python ~/.codex/skills/pet-animation-stabilizer/scripts/stabilize_pet_frames.py \
  --hatch-run /path/to/hatch-run \
  --candidate-dir /path/to/hatch-run-animation-stabilized
```

The candidate folder will include:

```text
original/
extracted-raw-frames/
frames-stabilized/
final/spritesheet.webp
qa/stability-report.json
qa/contact-sheet.png
qa/videos/
qa/candidate-summary.json
```

## Best Entry Point

Use this skill after a pet has already been hatched. This keeps the original result available for comparison and avoids interrupting the normal hatch-pet workflow.

The best source is a full hatch-pet run with:

```text
run/decoded/*.png
```

If `decoded/` is unavailable, the skill can also work from extracted frames or an existing `spritesheet.webp`, but optimization is less precise because some original row-strip information has already been lost.

## Notes

- This skill does not replace `$imagegen`.
- It does not mutate `imagegen-jobs.json`, `decoded/`, or installed pet files.
- Package or overwrite an installed pet only after reviewing the optimized candidate.

