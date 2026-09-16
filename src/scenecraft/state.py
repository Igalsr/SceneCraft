from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from .errors import ContractError
from .util import atomic_write_json, read_json, utc_now


class Stage(StrEnum):
    INGEST_REFERENCES = "ingest_references"
    ANALYZE_REFERENCES = "analyze_references"
    PLAN_GEOMETRY = "plan_geometry"
    BUILD_GEOMETRY = "build_geometry"
    RENDER_EVIDENCE = "render_evidence"
    EVALUATE_FIDELITY = "evaluate_fidelity"
    REPAIR_MODEL = "repair_model"
    PACKAGE_DELIVERABLE = "package_deliverable"
    LEARN_FROM_RUN = "learn_from_run"
    COMPLETE = "complete"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


ALLOWED_TRANSITIONS: dict[Stage, set[Stage]] = {
    Stage.INGEST_REFERENCES: {Stage.ANALYZE_REFERENCES},
    Stage.ANALYZE_REFERENCES: {Stage.PLAN_GEOMETRY},
    Stage.PLAN_GEOMETRY: {Stage.BUILD_GEOMETRY},
    Stage.BUILD_GEOMETRY: {Stage.RENDER_EVIDENCE},
    Stage.RENDER_EVIDENCE: {Stage.EVALUATE_FIDELITY},
    Stage.EVALUATE_FIDELITY: {Stage.REPAIR_MODEL, Stage.PACKAGE_DELIVERABLE},
    Stage.REPAIR_MODEL: {Stage.BUILD_GEOMETRY},
    Stage.PACKAGE_DELIVERABLE: {Stage.LEARN_FROM_RUN},
    Stage.LEARN_FROM_RUN: {Stage.COMPLETE},
    Stage.COMPLETE: set(),
}


@dataclass
class RunState:
    run_id: str
    project_id: str
    current_stage: Stage = Stage.INGEST_REFERENCES
    status: RunStatus = RunStatus.PENDING
    completed_stages: list[str] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 8
    project_digest: str = ""
    reference_digests: list[str] = field(default_factory=list)
    artifacts: dict[str, dict[str, str]] = field(default_factory=dict)
    message: str = ""
    last_error: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def transition(self, next_stage: Stage, *, message: str = "") -> None:
        if next_stage not in ALLOWED_TRANSITIONS[self.current_stage]:
            raise ContractError(f"Invalid transition: {self.current_stage} -> {next_stage}")
        if next_stage == Stage.COMPLETE:
            required = {"accepted_evaluation", "deliverable_manifest", "learning_report"}
            missing = sorted(required - self.artifacts.keys())
            if missing:
                raise ContractError(
                    f"Run cannot complete without artifacts: {', '.join(missing)}"
                )
        if self.current_stage.value not in self.completed_stages:
            self.completed_stages.append(self.current_stage.value)
        if self.current_stage == Stage.REPAIR_MODEL:
            self.iteration += 1
            if self.iteration > self.max_iterations:
                raise ContractError("Repair iteration limit exceeded")
        self.current_stage = next_stage
        self.status = RunStatus.COMPLETED if next_stage == Stage.COMPLETE else RunStatus.RUNNING
        self.message = message
        self.last_error = None
        self.updated_at = utc_now()

    def wait(self, message: str) -> None:
        self.status = RunStatus.WAITING
        self.message = message
        self.updated_at = utc_now()

    def fail(self, error: str) -> None:
        self.status = RunStatus.FAILED
        self.last_error = error
        self.message = error
        self.updated_at = utc_now()

    def record_artifact(self, name: str, relative_path: str, sha256: str) -> None:
        self.artifacts[name] = {"path": relative_path, "sha256": sha256}
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["current_stage"] = self.current_stage.value
        value["status"] = self.status.value
        return value

    def save(self, path: Path) -> None:
        atomic_write_json(path, self.to_dict())

    @classmethod
    def load(cls, path: Path) -> RunState:
        value = read_json(path)
        try:
            value["current_stage"] = Stage(value["current_stage"])
            value["status"] = RunStatus(value["status"])
            return cls(**value)
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError(f"Invalid run state at {path}: {exc}") from exc
