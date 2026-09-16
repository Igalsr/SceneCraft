from __future__ import annotations

import re
import shutil
import warnings
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .contracts import validate_project
from .errors import ContractError, SceneCraftError
from .util import atomic_write_json, read_json, resolve_inside, sha256_file

PROJECT_FILE = Path(".scenecraft/project.json")
REFERENCE_MANIFEST = Path(".scenecraft/reference-manifest.json")
ALLOWED_REFERENCE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _inspect_image(path: Path, suffix: str) -> dict[str, Any]:
    expected = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}[suffix]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                width, height = image.size
                actual = image.format
                if width * height > 100_000_000:
                    raise SceneCraftError("Reference image exceeds the 100 megapixel safety limit")
                image.verify()
            with Image.open(path) as image:
                image.load()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise SceneCraftError(f"Reference image cannot be decoded safely: {path}: {exc}") from exc
    if actual != expected:
        raise SceneCraftError(f"Reference contents are {actual or 'unknown'}, not {expected}")
    if width < 16 or height < 16:
        raise SceneCraftError("Reference images must be at least 16 by 16 pixels")
    return {"width": width, "height": height, "format": actual.lower()}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if len(slug) < 3:
        slug = f"project-{slug or 'new'}"
    return slug[:64].rstrip("-")


class Project:
    def __init__(self, root: Path):
        self.root = root.resolve()

    @classmethod
    def create(cls, root: Path, name: str, workflow: str = "hero-view", asset_type: str = "building") -> Project:
        project = cls(root)
        if (project.root / PROJECT_FILE).exists():
            raise SceneCraftError(f"A SceneCraft project already exists at {project.root}")
        if workflow not in {"hero-view", "multi-view", "metric"}:
            raise SceneCraftError(f"Unsupported workflow: {workflow}")
        if asset_type not in {"building", "object", "positive-master"}:
            raise SceneCraftError("Unsupported asset type")
        for relative in (
            ".scenecraft",
            ".scenecraft/learning",
            "inputs/references",
            "runs",
            "artifacts",
            "deliverables",
        ):
            (project.root / relative).mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            project.root / PROJECT_FILE,
            {
                "schema_version": 1,
                "project_id": slugify(name),
                "name": name,
                "workflow": workflow,
                "asset_type": asset_type,
                "units": "meters",
                "max_iterations": 8 if workflow == "hero-view" else 12,
                "acceptance": {
                    "silhouette_iou": 0.92,
                    "edge_f1": 0.86,
                    "perceptual_similarity": 0.88,
                },
            },
        )
        atomic_write_json(
            project.root / REFERENCE_MANIFEST,
            {"schema_version": 2, "references": []},
        )
        atomic_write_json(
            project.root / ".scenecraft/learning/lessons.json",
            {"schema_version": 2, "lessons": []},
        )
        atomic_write_json(
            project.root / ".scenecraft/learning/workflow-lessons.json",
            {"schema_version": 2, "lessons": []},
        )
        return project

    @classmethod
    def open(cls, root: Path) -> Project:
        project = cls(root)
        if not (project.root / PROJECT_FILE).is_file():
            raise SceneCraftError(f"No SceneCraft project found at {project.root}")
        project.config()
        return project

    def config(self) -> dict[str, Any]:
        try:
            return validate_project(read_json(self.root / PROJECT_FILE))
        except ValueError as exc:
            raise ContractError(str(exc)) from exc

    def references(self) -> dict[str, Any]:
        try:
            manifest = read_json(self.root / REFERENCE_MANIFEST)
        except ValueError as exc:
            raise ContractError(str(exc)) from exc
        if set(manifest) != {"schema_version", "references"}:
            raise ContractError("Invalid reference manifest fields")
        if manifest.get("schema_version") != 2 or not isinstance(manifest.get("references"), list):
            raise ContractError("Invalid reference manifest")
        required = {
            "id", "file", "sha256", "role", "view", "notes", "immutable",
            "width", "height", "format",
        }
        for index, reference in enumerate(manifest["references"]):
            if not isinstance(reference, dict) or set(reference) != required:
                raise ContractError(f"Invalid reference entry at index {index}")
            if reference["role"] not in {"primary", "supporting", "material", "scale"}:
                raise ContractError(f"Invalid reference role at index {index}")
            if reference["immutable"] is not True:
                raise ContractError(f"Reference {index} is not immutable")
            try:
                path = resolve_inside(self.root, self.root / reference["file"])
            except ValueError as exc:
                raise ContractError(str(exc)) from exc
            if (self.root / "inputs/references").resolve() not in path.parents:
                raise ContractError(f"Reference path is outside inputs/references: {path}")
        return manifest

    def add_reference(self, source: Path, role: str, view: str, notes: str = "") -> dict[str, Any]:
        source = source.resolve()
        if not source.is_file():
            raise SceneCraftError(f"Reference image not found: {source}")
        suffix = source.suffix.lower()
        if suffix not in ALLOWED_REFERENCE_SUFFIXES:
            raise SceneCraftError("References must be PNG, JPEG, or WebP images")
        image_info = _inspect_image(source, suffix)
        if role not in {"primary", "supporting", "material", "scale"}:
            raise SceneCraftError(f"Unsupported reference role: {role}")
        if not view.strip():
            raise SceneCraftError("Reference view must be non-empty")

        digest = sha256_file(source)
        manifest = self.references()
        for existing in manifest["references"]:
            if (
                existing["sha256"] == digest
                and existing["role"] == role
                and existing["view"] == view
            ):
                return existing

        destination = self.root / "inputs/references" / f"{digest[:12]}-{source.name}"
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        reference = {
            "id": f"ref-{len(manifest['references']) + 1:03d}",
            "file": destination.relative_to(self.root).as_posix(),
            "sha256": digest,
            "role": role,
            "view": view,
            "notes": notes.strip(),
            "immutable": True,
            **image_info,
        }
        manifest["references"].append(reference)
        atomic_write_json(self.root / REFERENCE_MANIFEST, manifest)
        return reference
