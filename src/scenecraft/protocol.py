from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import ContractError
from .util import atomic_write_json, read_json, resolve_inside

OPERATION_IO = {
    "build_object": (
        {"building_spec"},
        {"blend", "glb", "preview", "scene_manifest", "result", "stl", "geometry_report", "inspection_back", "inspection_side", "inspection_top"},
    ),
    "build_scene": (
        {"building_spec"},
        {"blend", "glb", "preview", "scene_manifest", "result"},
    ),
}


def _safe_path(root: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{field} must be a non-empty absolute path")
    path = Path(value)
    if not path.is_absolute():
        raise ContractError(f"{field} must be absolute")
    try:
        return resolve_inside(root, path)
    except ValueError as exc:
        raise ContractError(str(exc)) from exc


@dataclass(frozen=True)
class JobRequest:
    job_id: str
    operation: str
    workspace_root: str
    inputs: dict[str, str]
    outputs: dict[str, str]
    settings: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 2

    def validate(self) -> None:
        if self.schema_version != 2:
            raise ContractError("Unsupported job schema version")
        if self.operation not in OPERATION_IO:
            raise ContractError(f"Unsupported worker operation: {self.operation}")
        if not isinstance(self.job_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", self.job_id):
            raise ContractError("job_id is invalid")
        root = Path(self.workspace_root)
        if not root.is_absolute():
            raise ContractError("workspace_root must be absolute")
        root = root.resolve()
        if not isinstance(self.inputs, dict) or not isinstance(self.outputs, dict):
            raise ContractError("inputs and outputs must be objects")
        required_inputs, required_outputs = OPERATION_IO[self.operation]
        if set(self.inputs) != required_inputs:
            raise ContractError(f"{self.operation} inputs must be exactly {sorted(required_inputs)}")
        if set(self.outputs) != required_outputs:
            raise ContractError(f"{self.operation} outputs must be exactly {sorted(required_outputs)}")
        for name, value in self.inputs.items():
            _safe_path(root, value, f"inputs.{name}")
        for name, value in self.outputs.items():
            _safe_path(root, value, f"outputs.{name}")
        if not isinstance(self.settings, dict) or set(self.settings) - {"render_width", "render_height"}:
            raise ContractError("settings contains unsupported fields")
        for setting_name in ("render_width", "render_height"):
            number = self.settings.get(setting_name, 640)
            if isinstance(number, bool) or not isinstance(number, int) or not 64 <= number <= 4096:
                raise ContractError(f"settings.{setting_name} must be an integer from 64 to 4096")

    def save(self, path: Path) -> None:
        self.validate()
        atomic_write_json(path, asdict(self))

    @classmethod
    def load(cls, path: Path) -> JobRequest:
        try:
            value = read_json(path)
            if set(value) != {"job_id", "operation", "workspace_root", "inputs", "outputs", "settings", "schema_version"}:
                raise ContractError("Job request fields do not match the public contract")
            request = cls(**value)
        except (TypeError, ValueError) as exc:
            raise ContractError(f"Invalid job request at {path}: {exc}") from exc
        request.validate()
        root = Path(request.workspace_root).resolve()
        try:
            resolve_inside(root, path)
        except ValueError as exc:
            raise ContractError(str(exc)) from exc
        return request


@dataclass(frozen=True)
class JobResult:
    job_id: str
    status: str
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    schema_version: int = 2

    def validate(self) -> None:
        if self.schema_version != 2 or self.status not in {"succeeded", "failed"}:
            raise ContractError("Invalid worker result")
        if not isinstance(self.job_id, str) or not self.job_id:
            raise ContractError("Worker result job_id is required")
        if not isinstance(self.artifacts, list):
            raise ContractError("Worker result artifacts must be an array")
        seen: set[str] = set()
        for index, artifact in enumerate(self.artifacts):
            if not isinstance(artifact, dict) or set(artifact) != {"name", "path", "sha256"}:
                raise ContractError(f"Invalid artifact at index {index}")
            if not isinstance(artifact["name"], str) or not artifact["name"] or artifact["name"] in seen:
                raise ContractError(f"Invalid or duplicate artifact name at index {index}")
            seen.add(artifact["name"])
            if not isinstance(artifact["path"], str) or not artifact["path"]:
                raise ContractError(f"Invalid artifact path at index {index}")
            if not isinstance(artifact["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", artifact["sha256"]):
                raise ContractError(f"Invalid artifact digest at index {index}")
        if not isinstance(self.metrics, dict):
            raise ContractError("Worker result metrics must be an object")
        for key, value in self.metrics.items():
            if not isinstance(key, str) or isinstance(value, float) and not math.isfinite(value):
                raise ContractError("Worker result contains invalid metrics")
        if not isinstance(self.warnings, list) or not all(isinstance(item, str) for item in self.warnings):
            raise ContractError("Worker result warnings must be strings")
        if self.error is not None and not isinstance(self.error, str):
            raise ContractError("Worker result error must be text or null")

    def save(self, path: Path) -> None:
        self.validate()
        atomic_write_json(path, asdict(self))

    @classmethod
    def load(cls, path: Path) -> JobResult:
        try:
            value = read_json(path)
            if set(value) != {"job_id", "status", "artifacts", "metrics", "warnings", "error", "schema_version"}:
                raise ContractError("Worker result fields do not match the public contract")
            result = cls(**value)
        except (TypeError, ValueError) as exc:
            raise ContractError(f"Invalid job result at {path}: {exc}") from exc
        result.validate()
        return result
