from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat

from .errors import SceneCraftError
from .util import atomic_write_json

METRICS = ("silhouette_iou", "edge_f1", "perceptual_similarity")


def _pixels(image: Image.Image):
    getter = getattr(image, "get_flattened_data", image.getdata)
    return getter()


def _fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)


def _border_rgb(image: Image.Image) -> tuple[int, int, int]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = [rgb.getpixel((0, 0)), rgb.getpixel((width - 1, 0)), rgb.getpixel((0, height - 1)), rgb.getpixel((width - 1, height - 1))]
    return tuple(sum(pixel[channel] for pixel in pixels) // 4 for channel in range(3))


def _foreground_mask(image: Image.Image) -> Image.Image:
    if image.mode == "RGBA":
        alpha = image.getchannel("A")
        if alpha.getextrema() != (255, 255):
            return alpha.point(lambda value: 255 if value >= 16 else 0)
    rgb = image.convert("RGB")
    background = _border_rgb(rgb)
    pixels = []
    for red, green, blue in _pixels(rgb):
        distance = abs(red - background[0]) + abs(green - background[1]) + abs(blue - background[2])
        pixels.append(255 if distance >= 54 else 0)
    mask = Image.new("L", rgb.size)
    mask.putdata(pixels)
    return mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))


def _iou(left: Image.Image, right: Image.Image) -> float:
    intersection = ImageChops.multiply(left, right)
    union = ImageChops.lighter(left, right)
    union_count = sum(1 for value in _pixels(union) if value)
    if union_count == 0:
        return 1.0
    return sum(1 for value in _pixels(intersection) if value) / union_count


def _edge_mask(image: Image.Image) -> Image.Image:
    edges = image.convert("L").filter(ImageFilter.FIND_EDGES)
    return edges.point(lambda value: 255 if value >= 24 else 0)


def _edge_f1(left: Image.Image, right: Image.Image) -> float:
    left_edge = _edge_mask(left)
    right_edge = _edge_mask(right)
    left_values = list(_pixels(left_edge))
    right_values = list(_pixels(right_edge))
    left_count = sum(bool(value) for value in left_values)
    right_count = sum(bool(value) for value in right_values)
    if left_count == 0 and right_count == 0:
        return 1.0
    right_near = list(_pixels(right_edge.filter(ImageFilter.MaxFilter(5))))
    left_near = list(_pixels(left_edge.filter(ImageFilter.MaxFilter(5))))
    precision = sum(bool(value) and bool(right_near[index]) for index, value in enumerate(left_values)) / max(left_count, 1)
    recall = sum(bool(value) and bool(left_near[index]) for index, value in enumerate(right_values)) / max(right_count, 1)
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def _perceptual_similarity(left: Image.Image, right: Image.Image) -> float:
    difference = ImageChops.difference(left.convert("RGB"), right.convert("RGB"))
    mean = sum(ImageStat.Stat(difference).mean) / 3
    return max(0.0, 1.0 - mean / 255.0)


def evaluate_hero_view(
    *,
    reference_path: Path,
    render_path: Path,
    evaluation_path: Path,
    comparison_path: Path,
    reference_id: str,
    reference_view: str,
    iteration: int,
    thresholds: dict[str, float],
    hard_checks: dict[str, tuple[bool, str]],
) -> dict[str, Any]:
    try:
        with Image.open(reference_path) as source:
            reference = source.convert("RGBA")
        with Image.open(render_path) as source:
            render = source.convert("RGBA")
    except OSError as exc:
        raise SceneCraftError(f"Cannot evaluate image evidence: {exc}") from exc
    scale = min(1, 640 / max(reference.size))
    target_width = max(1, round(reference.width * scale))
    target_height = max(1, round(reference.height * scale))
    target_size = (target_width, target_height)
    reference = _fit(reference, target_size)
    render = _fit(render, target_size)
    reference_mask = _foreground_mask(reference)
    background_rgb = (255, 255, 255) if reference.getchannel("A").getextrema() != (255, 255) else _border_rgb(reference)
    background = Image.new("RGBA", target_size, (*background_rgb, 255))
    reference = Image.alpha_composite(background, reference).convert("RGB")
    rendered_rgb = Image.alpha_composite(background, render).convert("RGB")
    metrics = {
        "silhouette_iou": round(_iou(reference_mask, _foreground_mask(render)), 6),
        "edge_f1": round(_edge_f1(reference, rendered_rgb), 6),
        "perceptual_similarity": round(_perceptual_similarity(reference, rendered_rgb), 6),
    }
    metric_passes = {name: metrics[name] >= float(thresholds[name]) for name in METRICS}
    checks = [
        {"name": name, "passed": passed, "detail": detail}
        for name, (passed, detail) in sorted(hard_checks.items())
    ]
    accepted = all(metric_passes.values()) and all(item["passed"] for item in checks)
    priorities = [name for name in METRICS if not metric_passes[name]]
    evaluation = {
        "schema_version": 3,
        "iteration": iteration,
        "views": [
            {
                "reference_id": reference_id,
                "view": reference_view,
                "reference_path": str(reference_path),
                "render_path": str(render_path),
                "metrics": metrics,
                "thresholds": {name: float(thresholds[name]) for name in METRICS},
                "passed": all(metric_passes.values()),
            }
        ],
        "hard_checks": checks,
        "aggregate_score": round(sum(metrics.values()) / len(metrics), 6),
        "metrics_passed": accepted,
        "visual_review": None,
        "accepted": False,
        "repair_priorities": priorities,
    }
    comparison_path.parent.mkdir(parents=True, exist_ok=True)
    comparison = Image.new("RGB", (target_width * 3, target_height), "white")
    comparison.paste(reference, (0, 0))
    comparison.paste(rendered_rgb, (target_width, 0))
    comparison.paste(ImageChops.difference(reference, rendered_rgb), (target_width * 2, 0))
    comparison.save(comparison_path, format="PNG")
    atomic_write_json(evaluation_path, evaluation)
    return evaluation
