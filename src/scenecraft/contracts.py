from __future__ import annotations

import math
import re
from typing import Any

from .errors import ContractError

WORKFLOWS = {"hero-view", "multi-view", "metric"}
MATERIAL_KEYS = {"wall", "roof", "glass", "accent"}
FACADES = {"front", "back", "left", "right"}


def validate_scene_spec(value):
    if isinstance(value, dict) and value.get("kind") in {"object", "positive-master"}:
        from .object_contract import validate_object_spec
        return validate_object_spec(value)
    return validate_building_spec(value)


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{field} must be an object")
    return value


def _exact_keys(
    value: dict[str, Any],
    field: str,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - required - optional)
    if missing:
        raise ContractError(f"{field} is missing: {', '.join(missing)}")
    if unknown:
        raise ContractError(f"{field} has unsupported fields: {', '.join(unknown)}")


def _text(value: Any, field: str, *, max_length: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be non-empty text")
    if len(value) > max_length:
        raise ContractError(f"{field} must be no longer than {max_length} characters")
    return value


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ContractError(f"{field} must be finite")
    if positive and number <= 0:
        raise ContractError(f"{field} must be greater than zero")
    return number


def _vector(value: Any, field: str, length: int, *, positive: bool = False) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise ContractError(f"{field} must contain exactly {length} numbers")
    return [
        _number(item, f"{field}[{index}]", positive=positive)
        for index, item in enumerate(value)
    ]


def _color3(value: Any, field: str) -> list[float]:
    color = _vector(value, field, 3)
    if any(component < 0 or component > 1 for component in color):
        raise ContractError(f"{field} components must be between 0 and 1")
    return color


def _unique_id(value: Any, field: str, seen: set[str]) -> str:
    identifier = _text(value, field, max_length=80)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", identifier):
        raise ContractError(f"{field} contains unsupported characters")
    if identifier in seen:
        raise ContractError(f"Duplicate object id: {identifier}")
    seen.add(identifier)
    return identifier


def validate_building_spec(value: dict[str, Any]) -> dict[str, Any]:
    value = _object(value, "building specification")
    required = {
        "schema_version", "name", "units", "envelope", "floors",
        "wall_thickness", "camera", "materials", "uncertainties",
    }
    optional = {"volumes", "openings", "elements", "roof"}
    _exact_keys(value, "building specification", required, optional)
    if value["schema_version"] != 1:
        raise ContractError("Unsupported building specification schema_version")
    if value["units"] != "meters":
        raise ContractError("Building specification units must be meters")
    _text(value["name"], "name", max_length=160)

    envelope = _object(value["envelope"], "envelope")
    _exact_keys(envelope, "envelope", {"width", "depth", "height"})
    for field in ("width", "depth", "height"):
        _number(envelope[field], f"envelope.{field}", positive=True)
    floors = value["floors"]
    if isinstance(floors, bool) or not isinstance(floors, int) or not 1 <= floors <= 200:
        raise ContractError("floors must be an integer from 1 to 200")
    thickness = _number(value["wall_thickness"], "wall_thickness", positive=True)
    if thickness >= min(float(envelope["width"]), float(envelope["depth"])) / 2:
        raise ContractError("wall_thickness is too large for the envelope")

    camera = _object(value["camera"], "camera")
    _exact_keys(camera, "camera", {"position", "target", "lens_mm"})
    position = _vector(camera["position"], "camera.position", 3)
    target = _vector(camera["target"], "camera.target", 3)
    if position == target:
        raise ContractError("camera.position and camera.target must differ")
    lens = _number(camera["lens_mm"], "camera.lens_mm", positive=True)
    if not 10 <= lens <= 300:
        raise ContractError("camera.lens_mm must be from 10 to 300")

    materials = _object(value["materials"], "materials")
    _exact_keys(materials, "materials", {"wall_rgb", "roof_rgb", "glass_rgb"}, {"accent_rgb"})
    for field in ("wall_rgb", "roof_rgb", "glass_rgb"):
        _color3(materials[field], f"materials.{field}")
    if "accent_rgb" in materials:
        _color3(materials["accent_rgb"], "materials.accent_rgb")

    seen: set[str] = set()
    volumes = value.get("volumes", [])
    if not isinstance(volumes, list) or len(volumes) > 200:
        raise ContractError("volumes must be an array with at most 200 items")
    for index, item in enumerate(volumes):
        item = _object(item, f"volumes[{index}]")
        _exact_keys(item, f"volumes[{index}]", {"id", "center", "dimensions", "material"}, {"rotation_deg"})
        _unique_id(item["id"], f"volumes[{index}].id", seen)
        _vector(item["center"], f"volumes[{index}].center", 3)
        _vector(item["dimensions"], f"volumes[{index}].dimensions", 3, positive=True)
        if item["material"] not in MATERIAL_KEYS:
            raise ContractError(f"volumes[{index}].material is unsupported")
        _number(item.get("rotation_deg", 0), f"volumes[{index}].rotation_deg")

    openings = value.get("openings", [])
    if not isinstance(openings, list) or len(openings) > 1000:
        raise ContractError("openings must be an array with at most 1000 items")
    for index, item in enumerate(openings):
        item = _object(item, f"openings[{index}]")
        _exact_keys(item, f"openings[{index}]", {"id", "kind", "facade", "center", "width", "height"}, {"frame_width"})
        _unique_id(item["id"], f"openings[{index}].id", seen)
        if item["kind"] not in {"window", "door"}:
            raise ContractError(f"openings[{index}].kind must be window or door")
        if item["facade"] not in FACADES:
            raise ContractError(f"openings[{index}].facade is unsupported")
        _vector(item["center"], f"openings[{index}].center", 2)
        _number(item["width"], f"openings[{index}].width", positive=True)
        _number(item["height"], f"openings[{index}].height", positive=True)
        _number(item.get("frame_width", 0.08), f"openings[{index}].frame_width", positive=True)

    elements = value.get("elements", [])
    if not isinstance(elements, list) or len(elements) > 500:
        raise ContractError("elements must be an array with at most 500 items")
    for index, item in enumerate(elements):
        item = _object(item, f"elements[{index}]")
        _exact_keys(item, f"elements[{index}]", {"id", "semantic", "center", "dimensions", "material"}, {"rotation_deg"})
        _unique_id(item["id"], f"elements[{index}].id", seen)
        if item["semantic"] not in {"balcony", "canopy", "column", "screen", "trim"}:
            raise ContractError(f"elements[{index}].semantic is unsupported")
        _vector(item["center"], f"elements[{index}].center", 3)
        _vector(item["dimensions"], f"elements[{index}].dimensions", 3, positive=True)
        if item["material"] not in MATERIAL_KEYS:
            raise ContractError(f"elements[{index}].material is unsupported")
        _number(item.get("rotation_deg", 0), f"elements[{index}].rotation_deg")

    roof = _object(value.get("roof", {"type": "flat"}), "roof")
    _exact_keys(roof, "roof", {"type"}, {"overhang", "pitch_degrees"})
    if roof["type"] not in {"flat", "gable"}:
        raise ContractError("roof.type must be flat or gable")
    if _number(roof.get("overhang", 0), "roof.overhang") < 0:
        raise ContractError("roof.overhang cannot be negative")
    pitch = _number(roof.get("pitch_degrees", 30), "roof.pitch_degrees")
    if roof["type"] == "gable" and not 1 <= pitch <= 75:
        raise ContractError("gable roof pitch_degrees must be from 1 to 75")

    uncertainties = value["uncertainties"]
    if not isinstance(uncertainties, list) or len(uncertainties) > 200:
        raise ContractError("uncertainties must be an array with at most 200 items")
    for index, item in enumerate(uncertainties):
        item = _object(item, f"uncertainties[{index}]")
        _exact_keys(item, f"uncertainties[{index}]", {"field", "reason", "confidence"})
        _text(item["field"], f"uncertainties[{index}].field", max_length=200)
        _text(item["reason"], f"uncertainties[{index}].reason")
        confidence = _number(item["confidence"], f"uncertainties[{index}].confidence")
        if not 0 <= confidence <= 1:
            raise ContractError(f"uncertainties[{index}].confidence must be between 0 and 1")
    return value


def validate_repair(value: dict[str, Any], *, iteration: int) -> dict[str, Any]:
    value = _object(value, "repair plan")
    _exact_keys(value, "repair plan", {"schema_version", "based_on_iteration", "changes", "building_spec"})
    if value["schema_version"] != 2:
        raise ContractError("Unsupported repair schema_version")
    if value["based_on_iteration"] != iteration:
        raise ContractError(f"Repair is based on iteration {value['based_on_iteration']}; expected {iteration}")
    changes = value["changes"]
    if not isinstance(changes, list) or not 1 <= len(changes) <= 100:
        raise ContractError("repair changes must contain from 1 to 100 items")
    for index, item in enumerate(changes):
        item = _object(item, f"changes[{index}]")
        _exact_keys(item, f"changes[{index}]", {"target", "reason"})
        _text(item["target"], f"changes[{index}].target", max_length=200)
        _text(item["reason"], f"changes[{index}].reason")
    validate_scene_spec(value["building_spec"])
    return value


def validate_project(value: dict[str, Any]) -> dict[str, Any]:
    value = _object(value, "project")
    required = {"schema_version", "project_id", "name", "workflow", "units", "acceptance"}
    _exact_keys(value, "project", required, {"max_iterations", "asset_type"})
    if value.get("asset_type", "building") not in {"building", "object", "positive-master"}:
        raise ContractError("Unsupported asset_type")
    if value["schema_version"] != 1 or value["units"] != "meters":
        raise ContractError("Project must use schema version 1 and meter units")
    _text(value["name"], "project.name", max_length=160)
    if not isinstance(value["project_id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", value["project_id"]):
        raise ContractError("project_id is invalid")
    if value["workflow"] not in WORKFLOWS:
        raise ContractError("Unknown workflow")
    max_iterations = value.get("max_iterations", 8)
    if isinstance(max_iterations, bool) or not isinstance(max_iterations, int) or not 1 <= max_iterations <= 30:
        raise ContractError("max_iterations must be an integer from 1 to 30")
    acceptance = _object(value["acceptance"], "acceptance")
    _exact_keys(acceptance, "acceptance", {"silhouette_iou", "edge_f1", "perceptual_similarity"})
    for field in ("silhouette_iou", "edge_f1", "perceptual_similarity"):
        score = _number(acceptance[field], f"acceptance.{field}")
        if not 0 <= score <= 1:
            raise ContractError(f"acceptance.{field} must be between 0 and 1")
    return value
