#!/usr/bin/env python3
"""Analyze and non-destructively stabilize Codex pet animation frames."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

CELL_WIDTH = 192
CELL_HEIGHT = 208
MAX_WIDTH = CELL_WIDTH - 10
MAX_HEIGHT = CELL_HEIGHT - 10
ALPHA_THRESHOLD = 16
DEFAULT_CELL_BASELINE = 203

ROW_SPECS = [
    ("idle", 0, 6),
    ("running-right", 1, 8),
    ("running-left", 2, 8),
    ("waving", 3, 4),
    ("jumping", 4, 5),
    ("failed", 5, 8),
    ("waiting", 6, 6),
    ("running", 7, 6),
    ("review", 8, 6),
]


def default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or "~/.codex").expanduser().resolve()


def default_hatch_skill_dir() -> Path:
    return default_codex_home() / "skills" / "hatch-pet"


def alpha_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    alpha = image.getchannel("A")
    mask = alpha.point(lambda value: 255 if value > ALPHA_THRESHOLD else 0)
    return mask.getbbox()


def alpha_area(image: Image.Image) -> int:
    alpha = image.getchannel("A")
    return sum(count for value, count in enumerate(alpha.histogram()) if value > ALPHA_THRESHOLD)


def alpha_anchor_x(image: Image.Image, bbox: tuple[int, int, int, int] | None) -> float:
    if bbox is None:
        return CELL_WIDTH / 2
    left, top, right, bottom = bbox
    alpha = image.getchannel("A")
    counts: list[tuple[int, int]] = []
    total = 0
    for x in range(left, right):
        column = alpha.crop((x, top, x + 1, bottom))
        count = sum(
            pixel_count
            for value, pixel_count in enumerate(column.histogram())
            if value > ALPHA_THRESHOLD
        )
        if count:
            counts.append((x, count))
            total += count
    if not counts:
        return (left + right) / 2
    midpoint = total / 2
    running = 0
    for x, count in counts:
        running += count
        if running >= midpoint:
            return float(x)
    return float(counts[-1][0])


def median(values: list[float]) -> float:
    return float(statistics.median(values)) if values else 0.0


def parse_hex_color(value: str) -> tuple[int, int, int]:
    value = value.strip()
    if len(value) != 7 or not value.startswith("#"):
        raise SystemExit(f"invalid chroma key color: {value}")
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def load_chroma_key(run_dir: Path) -> tuple[int, int, int]:
    request_path = run_dir / "pet_request.json"
    if request_path.is_file():
        request = json.loads(request_path.read_text(encoding="utf-8"))
        chroma_key = request.get("chroma_key")
        if isinstance(chroma_key, dict) and isinstance(chroma_key.get("hex"), str):
            return parse_hex_color(chroma_key["hex"])
    return parse_hex_color("#00FF00")


def color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))


def remove_chroma_background(
    image: Image.Image,
    chroma_key: tuple[int, int, int],
    threshold: float,
) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            red, green, blue, alpha = pixels[x, y]
            if color_distance((red, green, blue), chroma_key) <= threshold:
                pixels[x, y] = (red, green, blue, 0)
    return rgba


def connected_components(image: Image.Image) -> list[dict[str, object]]:
    alpha = image.getchannel("A")
    width, height = image.size
    data = alpha.tobytes()
    visited = bytearray(width * height)
    components: list[dict[str, object]] = []

    for start, alpha_value in enumerate(data):
        if alpha_value <= ALPHA_THRESHOLD or visited[start]:
            continue
        stack = [start]
        visited[start] = 1
        pixels: list[int] = []
        min_x = width
        min_y = height
        max_x = 0
        max_y = 0

        while stack:
            current = stack.pop()
            pixels.append(current)
            x = current % width
            y = current // width
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)

            for neighbor in (
                current - 1 if x > 0 else None,
                current + 1 if x + 1 < width else None,
                current - width if y > 0 else None,
                current + width if y + 1 < height else None,
            ):
                if neighbor is not None and not visited[neighbor] and data[neighbor] > ALPHA_THRESHOLD:
                    visited[neighbor] = 1
                    stack.append(neighbor)

        components.append(
            {
                "pixels": pixels,
                "area": len(pixels),
                "bbox": (min_x, min_y, max_x + 1, max_y + 1),
                "center_x": (min_x + max_x + 1) / 2,
            }
        )
    return components


def component_group_image(
    source: Image.Image,
    components: list[dict[str, object]],
    padding: int = 4,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    width, height = source.size
    min_x = max(0, min(component["bbox"][0] for component in components) - padding)
    min_y = max(0, min(component["bbox"][1] for component in components) - padding)
    max_x = min(width, max(component["bbox"][2] for component in components) + padding)
    max_y = min(height, max(component["bbox"][3] for component in components) + padding)
    output = Image.new("RGBA", (max_x - min_x, max_y - min_y), (0, 0, 0, 0))
    source_pixels = source.load()
    output_pixels = output.load()
    for component in components:
        for pixel_index in component["pixels"]:
            x = pixel_index % width
            y = pixel_index // width
            output_pixels[x - min_x, y - min_y] = source_pixels[x, y]
    return output, (min_x, min_y, max_x, max_y)


def extract_component_frames(
    strip: Image.Image,
    frame_count: int,
) -> list[tuple[Image.Image, tuple[int, int, int, int]]] | None:
    components = connected_components(strip)
    if not components:
        return None

    largest_area = max(component["area"] for component in components)
    seed_threshold = max(120, largest_area * 0.20)
    seeds = [component for component in components if component["area"] >= seed_threshold]
    if len(seeds) < frame_count:
        seeds = sorted(components, key=lambda component: component["area"], reverse=True)[
            :frame_count
        ]
    if len(seeds) < frame_count:
        return None

    seeds = sorted(
        sorted(seeds, key=lambda component: component["area"], reverse=True)[:frame_count],
        key=lambda component: component["center_x"],
    )
    seed_ids = {id(seed) for seed in seeds}
    groups: list[list[dict[str, object]]] = [[seed] for seed in seeds]
    noise_threshold = max(12, largest_area * 0.002)

    for component in components:
        if id(component) in seed_ids or component["area"] < noise_threshold:
            continue
        nearest_index = min(
            range(len(seeds)),
            key=lambda index: abs(seeds[index]["center_x"] - component["center_x"]),
        )
        groups[nearest_index].append(component)

    return [component_group_image(strip, group) for group in groups]


def extract_slot_frames(
    strip: Image.Image,
    frame_count: int,
) -> list[tuple[Image.Image, tuple[int, int, int, int]]]:
    slot_width = strip.width / frame_count
    frames = []
    for index in range(frame_count):
        left = round(index * slot_width)
        right = round((index + 1) * slot_width)
        crop = strip.crop((left, 0, right, strip.height))
        bbox = alpha_bbox(crop)
        if bbox is None:
            frames.append((crop, (left, 0, right, strip.height)))
            continue
        bbox_left, bbox_top, bbox_right, bbox_bottom = bbox
        frames.append((crop, (left + bbox_left, bbox_top, left + bbox_right, bbox_bottom)))
    return frames


def frame_info(
    *,
    image: Image.Image,
    index: int,
    file_path: Path,
    input_mode: str,
    source_bbox: tuple[int, int, int, int] | None = None,
    extraction_method: str | None = None,
) -> dict[str, object]:
    bbox = alpha_bbox(image)
    if bbox is None:
        width = height = area = center_x = bottom = 0
    else:
        left, top, right, bottom = bbox
        width = right - left
        height = bottom - top
        center_x = (left + right) / 2
        area = alpha_area(image)
    anchor_x = alpha_anchor_x(image, bbox)
    anchor_offset_x = anchor_x - bbox[0] if bbox is not None else 0
    source_center_x = None
    if source_bbox is not None:
        source_center_x = (source_bbox[0] + source_bbox[2]) / 2
        bottom = source_bbox[3]
    return {
        "index": index,
        "file": str(file_path),
        "image": image,
        "bbox": bbox,
        "source_bbox": source_bbox,
        "width": width,
        "height": height,
        "area": area,
        "center_x": center_x,
        "anchor_x": anchor_x,
        "anchor_offset_x": anchor_offset_x,
        "source_center_x": source_center_x,
        "bottom": bottom,
        "input_mode": input_mode,
        "extraction_method": extraction_method,
    }


def frame_files(root: Path, state: str) -> list[Path]:
    state_dir = root / state
    if not state_dir.is_dir():
        return []
    return sorted(
        path for path in state_dir.iterdir() if path.suffix.lower() in {".png", ".webp"}
    )


def split_atlas(atlas_path: Path, output_root: Path) -> Path:
    with Image.open(atlas_path) as opened:
        atlas = opened.convert("RGBA")
    if atlas.size != (CELL_WIDTH * 8, CELL_HEIGHT * 9):
        raise SystemExit(f"expected atlas 1536x1872, got {atlas.width}x{atlas.height}")
    for state, row, count in ROW_SPECS:
        state_dir = output_root / state
        state_dir.mkdir(parents=True, exist_ok=True)
        for column in range(count):
            crop = atlas.crop(
                (
                    column * CELL_WIDTH,
                    row * CELL_HEIGHT,
                    (column + 1) * CELL_WIDTH,
                    (row + 1) * CELL_HEIGHT,
                )
            )
            crop.save(state_dir / f"{column:02d}.png")
    return output_root


def load_rows_from_frames(frames_root: Path, input_mode: str) -> dict[str, list[dict[str, object]]]:
    rows: dict[str, list[dict[str, object]]] = {}
    for state, _row, expected_count in ROW_SPECS:
        files = frame_files(frames_root, state)
        if len(files) < expected_count:
            rows[state] = []
            continue
        frames = []
        for index, path in enumerate(files[:expected_count]):
            with Image.open(path) as opened:
                image = opened.convert("RGBA")
            frames.append(
                frame_info(
                    image=image,
                    index=index,
                    file_path=path,
                    input_mode=input_mode,
                )
            )
        rows[state] = frames
    return rows


def load_rows_from_decoded(
    run_dir: Path,
    raw_frames_root: Path,
    *,
    key_threshold: float,
) -> dict[str, list[dict[str, object]]]:
    decoded_dir = run_dir / "decoded"
    if not decoded_dir.is_dir():
        raise SystemExit(f"hatch run has no decoded directory: {decoded_dir}")
    chroma_key = load_chroma_key(run_dir)
    rows: dict[str, list[dict[str, object]]] = {}
    for state, _row, frame_count in ROW_SPECS:
        strip_path = decoded_dir / f"{state}.png"
        if not strip_path.is_file():
            raise SystemExit(f"missing decoded row strip for {state}: {strip_path}")
        with Image.open(strip_path) as opened:
            strip = remove_chroma_background(opened, chroma_key, key_threshold)
        extracted = extract_component_frames(strip, frame_count)
        method = "components"
        if extracted is None:
            extracted = extract_slot_frames(strip, frame_count)
            method = "slots"
        state_dir = raw_frames_root / state
        state_dir.mkdir(parents=True, exist_ok=True)
        frames = []
        for index, (image, source_bbox) in enumerate(extracted[:frame_count]):
            output = state_dir / f"{index:02d}.png"
            image.save(output)
            frames.append(
                frame_info(
                    image=image,
                    index=index,
                    file_path=output,
                    input_mode="decoded",
                    source_bbox=source_bbox,
                    extraction_method=method,
                )
            )
        rows[state] = frames
    return rows


def row_report(state: str, frames: list[dict[str, object]]) -> dict[str, object]:
    widths = [float(frame["width"]) for frame in frames if frame["bbox"]]
    heights = [float(frame["height"]) for frame in frames if frame["bbox"]]
    areas = [float(frame["area"]) for frame in frames if frame["bbox"]]
    centers = [float(frame["center_x"]) for frame in frames if frame["bbox"]]
    bottoms = [float(frame["bottom"]) for frame in frames if frame["bbox"]]
    max_width = max(widths, default=0.0)
    max_height = max(heights, default=0.0)
    row_scale = min(
        MAX_WIDTH / max_width if max_width else 1.0,
        MAX_HEIGHT / max_height if max_height else 1.0,
        1.0,
    )
    input_modes = sorted({str(frame.get("input_mode") or "") for frame in frames if frame})
    extraction_methods = sorted(
        {str(frame.get("extraction_method") or "") for frame in frames if frame.get("extraction_method")}
    )
    warnings: list[str] = []
    if not frames:
        warnings.append("missing frames for row")
    if row_scale < 1.0:
        warnings.append(f"row should use shared scale {row_scale:.3f}")
    if "slots" in extraction_methods:
        warnings.append("row fell back to slot extraction; visually inspect slicing")
    if areas:
        med_area = median(areas)
        for frame in frames:
            area = float(frame["area"])
            if med_area and area < med_area * 0.45:
                warnings.append(f"frame {frame['index']:02d} area is much smaller than row median")
            if med_area and area > med_area * 1.9:
                warnings.append(f"frame {frame['index']:02d} area is much larger than row median")
    if state != "jumping" and bottoms and "decoded" not in input_modes:
        if max(bottoms) - min(bottoms) > 6:
            warnings.append(f"baseline drifts {max(bottoms) - min(bottoms):.1f}px")
    if centers:
        if max(centers) - min(centers) > 12:
            warnings.append(f"subject center drifts {max(centers) - min(centers):.1f}px")
    return {
        "state": state,
        "frame_count": len(frames),
        "input_modes": input_modes,
        "extraction_methods": extraction_methods,
        "row_scale": row_scale,
        "median_area": median(areas),
        "median_center_x": median(centers),
        "median_bottom": median(bottoms),
        "max_width": max_width,
        "max_height": max_height,
        "warnings": warnings,
        "frames": [
            {
                "index": frame["index"],
                "file": frame["file"],
                "bbox": list(frame["bbox"]) if frame["bbox"] else None,
                "source_bbox": list(frame["source_bbox"]) if frame.get("source_bbox") else None,
                "width": frame["width"],
                "height": frame["height"],
                "area": frame["area"],
                "center_x": frame["center_x"],
                "anchor_x": frame.get("anchor_x"),
                "anchor_offset_x": frame.get("anchor_offset_x"),
                "source_center_x": frame.get("source_center_x"),
                "bottom": frame["bottom"],
            }
            for frame in frames
        ],
    }


def target_baseline(report: dict[str, object]) -> int:
    input_modes = report.get("input_modes")
    if isinstance(input_modes, list) and "decoded" in input_modes:
        return DEFAULT_CELL_BASELINE
    bottom = float(report.get("median_bottom") or 0)
    if 180 <= bottom <= CELL_HEIGHT:
        return int(round(bottom))
    return DEFAULT_CELL_BASELINE


def paste_normalized(
    frame: dict[str, object],
    *,
    row_scale: float,
    anchor_x: int,
    target_bottom: int,
) -> Image.Image:
    image = frame["image"]
    assert isinstance(image, Image.Image)
    bbox = frame["bbox"]
    target = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    if bbox is None:
        return target
    sprite = image.crop(bbox)
    if row_scale != 1.0:
        sprite = sprite.resize(
            (
                max(1, round(sprite.width * row_scale)),
                max(1, round(sprite.height * row_scale)),
            ),
            Image.Resampling.LANCZOS,
        )
    anchor_offset_x = float(frame.get("anchor_offset_x") or sprite.width / 2)
    left = int(round(anchor_x - anchor_offset_x * row_scale))
    top = int(round(target_bottom - sprite.height))
    left = max(0, min(CELL_WIDTH - sprite.width, left))
    top = max(0, min(CELL_HEIGHT - sprite.height, top))
    target.alpha_composite(sprite, (left, top))
    return target


def write_normalized_rows(
    rows: dict[str, list[dict[str, object]]],
    reports: dict[str, dict[str, object]],
    output_root: Path,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    for state, _row, expected_count in ROW_SPECS:
        frames = rows.get(state, [])
        report = reports[state]
        row_scale = float(report["row_scale"])
        baseline = target_baseline(report)
        anchor_x = 96
        state_dir = output_root / state
        state_dir.mkdir(parents=True, exist_ok=True)
        if state == "jumping":
            bottoms = [float(frame["bottom"]) for frame in frames if frame["bbox"]]
            source_baseline = (
                max(bottoms[0], bottoms[-1]) if len(bottoms) >= 2 else max(bottoms, default=baseline)
            )
            for frame in frames[:expected_count]:
                original_bottom = float(frame["bottom"])
                lift = max(0, source_baseline - original_bottom) * row_scale
                target_bottom = int(round(baseline - lift))
                normalized = paste_normalized(
                    frame,
                    row_scale=row_scale,
                    anchor_x=anchor_x,
                    target_bottom=target_bottom,
                )
                normalized.save(state_dir / f"{int(frame['index']):02d}.png")
        else:
            for frame in frames[:expected_count]:
                normalized = paste_normalized(
                    frame,
                    row_scale=row_scale,
                    anchor_x=anchor_x,
                    target_bottom=baseline,
                )
                normalized.save(state_dir / f"{int(frame['index']):02d}.png")


def build_report(
    rows: dict[str, list[dict[str, object]]],
    *,
    source: str,
    report_path: Path,
) -> dict[str, object]:
    reports = {state: row_report(state, rows.get(state, [])) for state, _row, _count in ROW_SPECS}
    result = {
        "ok": True,
        "source": source,
        "rows": list(reports.values()),
        "summary_warnings": [
            f"{state}: {warning}"
            for state, report in reports.items()
            for warning in report["warnings"]
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def copy_if_exists(source: Path, target: Path) -> str | None:
    if not source.exists():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)
    return str(target)


def unique_candidate_dir(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 100):
        candidate = path.with_name(f"{path.name}-{index}")
        if not candidate.exists():
            return candidate
    raise SystemExit(f"could not find available candidate directory near {path}")


def run_command(command: list[str]) -> None:
    print("+ " + " ".join(command))
    subprocess.run(command, check=True)


def compose_candidate(
    *,
    hatch_skill_dir: Path,
    frames_root: Path,
    candidate_dir: Path,
    skip_videos: bool,
    ffmpeg: str,
) -> dict[str, str | None]:
    scripts_dir = hatch_skill_dir / "scripts"
    compose = scripts_dir / "compose_atlas.py"
    validate = scripts_dir / "validate_atlas.py"
    contact = scripts_dir / "make_contact_sheet.py"
    videos = scripts_dir / "render_animation_videos.py"
    for script in (compose, validate, contact):
        if not script.is_file():
            raise SystemExit(f"missing hatch-pet script: {script}")

    final_dir = candidate_dir / "final"
    qa_dir = candidate_dir / "qa"
    final_dir.mkdir(parents=True, exist_ok=True)
    qa_dir.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            sys.executable,
            str(compose),
            "--frames-root",
            str(frames_root),
            "--output",
            str(final_dir / "spritesheet.png"),
            "--webp-output",
            str(final_dir / "spritesheet.webp"),
        ]
    )
    run_command(
        [
            sys.executable,
            str(validate),
            str(final_dir / "spritesheet.webp"),
            "--json-out",
            str(final_dir / "validation.json"),
        ]
    )
    run_command(
        [
            sys.executable,
            str(contact),
            str(final_dir / "spritesheet.webp"),
            "--output",
            str(qa_dir / "contact-sheet.png"),
        ]
    )
    video_dir: str | None = None
    if not skip_videos and videos.is_file():
        video_command = [
            sys.executable,
            str(videos),
            str(final_dir / "spritesheet.webp"),
            "--output-dir",
            str(qa_dir / "videos"),
        ]
        if ffmpeg:
            video_command.extend(["--ffmpeg", ffmpeg])
        run_command(video_command)
        video_dir = str(qa_dir / "videos")
    return {
        "spritesheet": str(final_dir / "spritesheet.webp"),
        "validation": str(final_dir / "validation.json"),
        "contact_sheet": str(qa_dir / "contact-sheet.png"),
        "videos": video_dir,
    }


def optimize_hatch_run(args: argparse.Namespace) -> None:
    run_dir = Path(args.hatch_run).expanduser().resolve()
    candidate_dir = (
        Path(args.candidate_dir).expanduser().resolve()
        if args.candidate_dir
        else unique_candidate_dir(run_dir.with_name(f"{run_dir.name}-animation-stabilized"))
    )
    if candidate_dir.exists() and not args.force:
        raise SystemExit(f"candidate directory already exists: {candidate_dir}; pass --force")
    if candidate_dir.exists():
        shutil.rmtree(candidate_dir)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    original_dir = candidate_dir / "original"
    original = {
        "spritesheet": copy_if_exists(run_dir / "final" / "spritesheet.webp", original_dir / "spritesheet.webp"),
        "spritesheet_png": copy_if_exists(run_dir / "final" / "spritesheet.png", original_dir / "spritesheet.png"),
        "contact_sheet": copy_if_exists(run_dir / "qa" / "contact-sheet.png", original_dir / "contact-sheet.png"),
        "videos": copy_if_exists(run_dir / "qa" / "videos", original_dir / "videos"),
        "run_summary": copy_if_exists(run_dir / "qa" / "run-summary.json", original_dir / "run-summary.json"),
    }

    raw_frames_root = candidate_dir / "extracted-raw-frames"
    rows = load_rows_from_decoded(
        run_dir,
        raw_frames_root,
        key_threshold=args.key_threshold,
    )
    report_path = candidate_dir / "qa" / "stability-report.json"
    report = build_report(rows, source=str(run_dir / "decoded"), report_path=report_path)
    stabilized_root = candidate_dir / "frames-stabilized"
    reports_by_state = {
        row["state"]: row for row in report["rows"] if isinstance(row, dict) and isinstance(row.get("state"), str)
    }
    write_normalized_rows(rows, reports_by_state, stabilized_root)

    optimized = compose_candidate(
        hatch_skill_dir=Path(args.hatch_skill_dir).expanduser().resolve(),
        frames_root=stabilized_root,
        candidate_dir=candidate_dir,
        skip_videos=args.skip_videos,
        ffmpeg=args.ffmpeg,
    )
    summary = {
        "ok": True,
        "source_run": str(run_dir),
        "candidate_dir": str(candidate_dir),
        "entry_point": "decoded",
        "original": original,
        "optimized": optimized,
        "raw_frames": str(raw_frames_root),
        "stabilized_frames": str(stabilized_root),
        "stability_report": str(report_path),
        "warnings": report["summary_warnings"],
    }
    summary_path = candidate_dir / "qa" / "candidate-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


def optimize_frames_or_atlas(args: argparse.Namespace) -> None:
    temp_dir: TemporaryDirectory[str] | None = None
    if args.atlas:
        temp_dir = TemporaryDirectory(prefix="pet-animation-frames-")
        frames_root = split_atlas(Path(args.atlas).expanduser().resolve(), Path(temp_dir.name))
        input_mode = "atlas"
        source = str(Path(args.atlas).expanduser().resolve())
    else:
        frames_root = Path(args.frames_root).expanduser().resolve()
        input_mode = "frames"
        source = str(frames_root)

    rows = load_rows_from_frames(frames_root, input_mode)
    report_path = Path(args.report).expanduser().resolve()
    report = build_report(rows, source=source, report_path=report_path)

    if args.output_root:
        reports_by_state = {
            row["state"]: row for row in report["rows"] if isinstance(row, dict) and isinstance(row.get("state"), str)
        }
        write_normalized_rows(rows, reports_by_state, Path(args.output_root).expanduser().resolve())

    print(json.dumps({"ok": True, "report": str(report_path), "warnings": len(report["summary_warnings"])}, indent=2))
    if temp_dir is not None:
        temp_dir.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--hatch-run")
    source.add_argument("--frames-root")
    source.add_argument("--atlas")
    parser.add_argument("--candidate-dir")
    parser.add_argument("--output-root")
    parser.add_argument("--report")
    parser.add_argument("--hatch-skill-dir", default=str(default_hatch_skill_dir()))
    parser.add_argument("--key-threshold", type=float, default=96.0)
    parser.add_argument("--skip-videos", action="store_true")
    parser.add_argument("--ffmpeg", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.hatch_run:
        optimize_hatch_run(args)
        return
    if not args.report:
        raise SystemExit("--report is required when using --frames-root or --atlas")
    optimize_frames_or_atlas(args)


if __name__ == "__main__":
    main()
