from __future__ import annotations

import math
import os
import uuid
from pathlib import Path
from typing import Any

from .errors import ContractError, SceneCraftError
from .project import Project
from .util import atomic_write_json, read_json, utc_now

PROJECT_MEMORY = Path(".scenecraft/learning/lessons.json")
LESSON_STATUSES = {"candidate", "validated", "deprecated"}


def _empty_memory() -> dict[str, Any]:
    return {"schema_version": 2, "lessons": []}


def _bounded_text(value: str, field: str, limit: int = 2000) -> str:
    value = value.strip()
    if not value:
        raise ContractError(f"{field} must be non-empty")
    if len(value) > limit:
        raise ContractError(f"{field} must be no longer than {limit} characters")
    return value


class LearningStore:
    """Evidence-backed memory for project and reusable workflow lessons."""

    def __init__(self, project: Project, workflow_memory: Path | None = None):
        self.project = project
        self.project_path = project.root / PROJECT_MEMORY
        configured = os.environ.get("SCENECRAFT_WORKFLOW_MEMORY")
        config_path = project.root / ".scenecraft/memory-config.json"
        if not configured and config_path.is_file():
            configured = read_json(config_path)["workflow_memory"]
        self.workflow_path = (
            workflow_memory
            or (Path(configured) if configured else project.root / ".scenecraft/learning/workflow-lessons.json")
        ).resolve()

    @staticmethod
    def initialize(path: Path) -> None:
        if not path.exists():
            atomic_write_json(path, _empty_memory())

    def initialize_report(self, run_id: str) -> Path:
        report_path = self.report_path(run_id)
        if not report_path.exists():
            atomic_write_json(
                report_path,
                {
                    "schema_version": 2,
                    "run_id": run_id,
                    "captured_at": utc_now(),
                    "completed": False,
                    "no_lessons_reason": None,
                    "lessons": [],
                },
            )
        return report_path

    def finalize_report(self, run_id: str, *, no_lessons_reason: str | None = None) -> Path:
        report_path = self.initialize_report(run_id)
        report = read_json(report_path)
        lessons = report.get("lessons", [])
        if not lessons:
            if no_lessons_reason is None:
                raise SceneCraftError(
                    "Record at least one lesson or provide an explicit no-lessons reason"
                )
            report["no_lessons_reason"] = _bounded_text(
                no_lessons_reason, "no_lessons_reason", 1000
            )
        elif no_lessons_reason is not None:
            raise ContractError("no_lessons_reason is only valid when the report has no lessons")
        report["completed"] = True
        report["captured_at"] = utc_now()
        atomic_write_json(report_path, report)
        return report_path

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return _empty_memory()
        value = read_json(path)
        if value.get("schema_version") not in {1, 2} or not isinstance(value.get("lessons"), list):
            raise ContractError(f"Invalid learning memory at {path}")
        value["schema_version"] = 2
        return value

    @staticmethod
    def _save(path: Path, memory: dict[str, Any]) -> None:
        atomic_write_json(path, memory)

    @staticmethod
    def _is_relevant(lesson: dict[str, Any], workflow: str) -> bool:
        evidence = lesson.get("evidence", {})
        delta = evidence.get("delta")
        supported = (
            evidence.get("kind", "measured") == "measured"
            and isinstance(delta, (int, float)) and not isinstance(delta, bool)
            and math.isfinite(delta) and delta > 0
            and not evidence.get("regressed_views")
        )
        return supported and lesson.get("status") == "validated" and (
            not lesson.get("workflow_scope") or workflow in lesson["workflow_scope"]
        )

    def applicable(self, workflow: str) -> list[dict[str, Any]]:
        """Return validated lessons, with project lessons overriding shared action keys."""
        selected: dict[str, dict[str, Any]] = {}
        for path in (self.workflow_path, self.project_path):
            memory = self._load(path)
            for lesson in memory["lessons"]:
                if not self._is_relevant(lesson, workflow):
                    continue
                selected[lesson["action_key"]] = dict(lesson)
        return sorted(
            selected.values(),
            key=lambda item: (float(item.get("confidence", 0)), item["action_key"]),
            reverse=True,
        )

    def mark_applied(self, lesson_ids: list[str], run_id: str) -> None:
        targets = set(lesson_ids)
        for path in (self.workflow_path, self.project_path):
            memory = self._load(path)
            changed = False
            for lesson in memory["lessons"]:
                if lesson.get("lesson_id") not in targets:
                    continue
                lesson["application_count"] = int(lesson.get("application_count", 0)) + 1
                lesson["last_applied_run_id"] = run_id
                lesson["updated_at"] = utc_now()
                changed = True
            if changed:
                self._save(path, memory)

    def catalog(self, *, include_candidates: bool = False) -> list[dict[str, Any]]:
        lessons: list[dict[str, Any]] = []
        for source, path in (("workflow", self.workflow_path), ("project", self.project_path)):
            for lesson in self._load(path)["lessons"]:
                if include_candidates or lesson.get("status") == "validated":
                    item = dict(lesson)
                    item["memory_scope"] = source
                    lessons.append(item)
        return sorted(lessons, key=lambda item: item.get("created_at", ""), reverse=True)

    def record_observation(self, run_id: str, *, action_key: str, learning: str, recommended_action: str) -> dict[str, Any]:
        """Preserve unmeasured lessons from failed runs without automatically activating them."""
        report_path = self.initialize_report(run_id)
        report = read_json(report_path)
        if report.get("completed"):
            raise SceneCraftError("The learning report is already complete")
        now = utc_now()
        lesson = {
            "lesson_id": f"lesson-{uuid.uuid4().hex[:12]}",
            "action_key": _bounded_text(action_key, "action_key", 120),
            "status": "candidate", "stage": "learn_from_run",
            "workflow_scope": [self.project.config()["workflow"]],
            "trigger": "Run retrospective without a measured before/after comparison",
            "learning": _bounded_text(learning, "learning"),
            "recommended_action": _bounded_text(recommended_action, "recommended_action"),
            "confidence": 0.0,
            "evidence": {"kind": "observation", "run_id": run_id, "before_score": None, "after_score": None, "delta": None, "regressed_views": [], "artifact_paths": [f"runs/{run_id}/state.json"]},
            "application_count": 0, "last_applied_run_id": None, "created_at": now, "updated_at": now,
        }
        memory = self._load(self.project_path)
        memory["lessons"].append(lesson)
        self._save(self.project_path, memory)
        report["lessons"].append({key: lesson[key] for key in ("lesson_id", "status", "action_key", "evidence") } | {"memory_scope": "project"})
        report["captured_at"] = now
        atomic_write_json(report_path, report)
        # Full text is preserved as immutable run evidence as well as project memory.
        atomic_write_json(report_path.parent / f"{lesson['lesson_id']}.json", lesson)
        return lesson

    def record_improvement(
        self,
        *,
        run_id: str,
        action_key: str,
        stage: str,
        trigger: str,
        learning: str,
        recommended_action: str,
        before_evaluation: dict[str, Any],
        after_evaluation: dict[str, Any],
        confidence: float,
        artifact_paths: list[str] | None = None,
        workflow_scope: list[str] | None = None,
        memory_scope: str = "project",
    ) -> dict[str, Any]:
        if memory_scope not in {"project", "workflow"}:
            raise ContractError("memory_scope must be project or workflow")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not math.isfinite(float(confidence)) or not 0 <= confidence <= 1:
            raise ContractError("confidence must be between 0 and 1")
        if not (self.project.root / "runs" / run_id / "state.json").is_file():
            raise SceneCraftError(f"Run does not exist: {run_id}")
        report_path = self.initialize_report(run_id)
        report = read_json(report_path)
        if report.get("completed"):
            raise SceneCraftError("The learning report is already complete")

        action_key = _bounded_text(action_key, "action_key", 120)
        stage = _bounded_text(stage, "stage", 80)
        trigger = _bounded_text(trigger, "trigger")
        learning = _bounded_text(learning, "learning")
        recommended_action = _bounded_text(recommended_action, "recommended_action")
        before_score = self._evaluation_score(before_evaluation, "before_evaluation")
        after_score = self._evaluation_score(after_evaluation, "after_evaluation")
        if after_evaluation["iteration"] <= before_evaluation["iteration"]:
            raise ContractError("after_evaluation must follow before_evaluation")
        regressions = self._regressed_views(before_evaluation, after_evaluation)
        workflow_scope = workflow_scope or [self.project.config()["workflow"]]
        improvement = after_score - before_score
        validated = improvement > 0 and not regressions and confidence >= 0.7
        now = utc_now()
        lesson = {
            "lesson_id": f"lesson-{uuid.uuid4().hex[:12]}",
            "action_key": action_key,
            "status": "validated" if validated else "candidate",
            "stage": stage,
            "workflow_scope": sorted(set(workflow_scope)),
            "trigger": trigger,
            "learning": learning,
            "recommended_action": recommended_action,
            "confidence": confidence,
            "evidence": {
                "kind": "measured",
                "run_id": run_id,
                "before_score": before_score,
                "after_score": after_score,
                "delta": round(improvement, 6),
                "regressed_views": regressions,
                "artifact_paths": artifact_paths or [],
            },
            "application_count": 0,
            "last_applied_run_id": None,
            "created_at": now,
            "updated_at": now,
        }

        destination = self.workflow_path if memory_scope == "workflow" else self.project_path
        memory = self._load(destination)
        if validated:
            for existing in memory["lessons"]:
                if (
                    existing.get("status") == "validated"
                    and existing.get("action_key") == action_key
                    and set(existing.get("workflow_scope", [])) & set(workflow_scope)
                ):
                    existing["status"] = "deprecated"
                    existing["updated_at"] = now
        memory["lessons"].append(lesson)
        self._save(destination, memory)

        report_path = self.report_path(run_id)
        if not report_path.is_file():
            self.initialize_report(run_id)
        report = read_json(report_path)
        if report.get("completed"):
            raise SceneCraftError("The learning report is already complete")
        report["captured_at"] = now
        report["lessons"].append(
            {
                "lesson_id": lesson["lesson_id"],
                "memory_scope": memory_scope,
                "status": lesson["status"],
                "action_key": action_key,
                "evidence": lesson["evidence"],
            }
        )
        atomic_write_json(report_path, report)
        atomic_write_json(report_path.parent / f"{lesson['lesson_id']}.json", lesson)
        return lesson

    @staticmethod
    def _evaluation_score(evaluation: dict[str, Any], field: str) -> float:
        if not isinstance(evaluation, dict) or evaluation.get("schema_version") not in {2, 3}:
            raise ContractError(f"{field} is not a SceneCraft evaluation")
        score = evaluation.get("aggregate_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)) or not 0 <= score <= 1:
            raise ContractError(f"{field}.aggregate_score is invalid")
        if not isinstance(evaluation.get("iteration"), int) or not isinstance(evaluation.get("views"), list):
            raise ContractError(f"{field} is incomplete")
        return float(score)

    @staticmethod
    def _regressed_views(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
        before_views = {item.get("view"): item for item in before["views"] if isinstance(item, dict)}
        regressions: list[str] = []
        for current in after["views"]:
            if not isinstance(current, dict) or current.get("view") not in before_views:
                continue
            previous = before_views[current["view"]]
            previous_metrics = previous.get("metrics", {})
            current_metrics = current.get("metrics", {})
            if any(
                isinstance(previous_metrics.get(name), (int, float))
                and isinstance(current_metrics.get(name), (int, float))
                and float(current_metrics[name]) + 1e-9 < float(previous_metrics[name])
                for name in ("silhouette_iou", "edge_f1", "perceptual_similarity")
            ):
                regressions.append(str(current["view"]))
        return sorted(set(regressions))

    def report_path(self, run_id: str) -> Path:
        return self.project.root / "runs" / run_id / "learning/report.json"
