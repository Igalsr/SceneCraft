from __future__ import annotations

import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import validate_repair, validate_scene_spec
from .errors import ContractError, SceneCraftError
from .evaluation import evaluate_hero_view
from .learning import LearningStore
from .project import PROJECT_FILE, REFERENCE_MANIFEST, Project
from .protocol import JobRequest, JobResult
from .state import RunState, RunStatus, Stage
from .util import (
    atomic_write_json,
    canonical_json_digest,
    read_json,
    resolve_inside,
    sha256_file,
    utc_now,
)
from .worker import BlenderWorker

RUN_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z-[a-f0-9]{8}$")


def new_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise SceneCraftError(f"Invalid run id: {run_id!r}")
    return run_id


class WorkflowEngine:
    def __init__(self, project: Project):
        self.project = project

    def run_dir(self, run_id: str) -> Path:
        validate_run_id(run_id)
        try:
            return resolve_inside(self.project.root / "runs", self.project.root / "runs" / run_id)
        except ValueError as exc:
            raise SceneCraftError(str(exc)) from exc

    def state_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "state.json"

    def load(self, run_id: str) -> RunState:
        path = self.state_path(run_id)
        if not path.is_file():
            raise SceneCraftError(f"Run does not exist: {run_id}")
        return RunState.load(path)

    def latest_run_id(self) -> str | None:
        runs = self.project.root / "runs"
        states = sorted(runs.glob("*/state.json")) if runs.is_dir() else []
        valid = [path for path in states if RUN_ID_PATTERN.fullmatch(path.parent.name)]
        return valid[-1].parent.name if valid else None

    def start(self, spec_path: Path | None = None) -> RunState:
        config = self.project.config()
        if config["workflow"] != "hero-view":
            raise SceneCraftError(
                f"Workflow {config['workflow']!r} is not executable in this release; use hero-view"
            )
        manifest = self.project.references()
        primary = [item for item in manifest["references"] if item["role"] == "primary"]
        if len(primary) != 1:
            raise SceneCraftError("hero-view requires exactly one primary reference; use supporting for other images")
        for reference in manifest["references"]:
            image = resolve_inside(self.project.root, self.project.root / reference["file"])
            if not image.is_file() or sha256_file(image) != reference["sha256"]:
                raise SceneCraftError(f"Reference failed immutability check: {reference['file']}")

        run_id = new_run_id()
        run_dir = self.run_dir(run_id)
        (run_dir / "inputs").mkdir(parents=True)
        shutil.copyfile(self.project.root / PROJECT_FILE, run_dir / "inputs/project.json")
        shutil.copyfile(self.project.root / REFERENCE_MANIFEST, run_dir / "inputs/reference-manifest.json")
        lessons = LearningStore(self.project).applicable(config["workflow"])
        applied_lessons_path = run_dir / "inputs/applied-lessons.json"
        atomic_write_json(applied_lessons_path, {"schema_version": 1, "run_id": run_id, "lessons": lessons})
        state = RunState(
            run_id=run_id,
            project_id=config["project_id"],
            max_iterations=config.get("max_iterations", 8),
            project_digest=canonical_json_digest(config),
            reference_digests=[item["sha256"] for item in manifest["references"]],
            status=RunStatus.RUNNING,
        )
        state.transition(Stage.ANALYZE_REFERENCES, message="References frozen and verified")
        request_path = run_dir / "analysis-request.json"
        atomic_write_json(
            request_path,
            {
                "schema_version": 3,
                "orchestrator": {"mode": "codex-agent", "required_model": "gpt-6-astra", "api_call": False},
                "project": config,
                "references": manifest["references"],
                "controlling_reference_id": primary[0]["id"],
                "validated_lessons": lessons,
                "expected_output_schema": "schemas/scene-spec.schema.json",
                "instructions": [
                    "Inspect every reference image in this active Astra/Codex task.",
                    "Use the primary reference as the locked hero view.",
                    "Use the scene schema matching project.asset_type; objects and positive masters use structured primitives or explicit mesh data.",
                    "For a positive master, obtain user dimensions and release strategy; never infer physical scale from a lone image.",
                    "Report hidden or uncertain geometry in uncertainties.",
                    "Write JSON only; never write Python or shell for Blender execution.",
                ],
            },
        )
        self._record(state, "analysis_request", request_path)
        self._record(state, "applied_lessons", applied_lessons_path)
        self._record(state, "frozen_project", run_dir / "inputs/project.json")
        self._record(state, "frozen_references", run_dir / "inputs/reference-manifest.json")
        state.save(self.state_path(run_id))
        if spec_path is not None:
            return self.accept_spec(run_id, read_json(spec_path), source="manual", lessons_applied=False)
        state.wait("Awaiting a building specification from the active Astra/Codex agent")
        state.save(self.state_path(run_id))
        return state

    def accept_spec(self, run_id: str, spec: dict[str, Any], *, source: str, lessons_applied: bool) -> RunState:
        state = self.load(run_id)
        self.verify_inputs(state)
        if state.current_stage != Stage.ANALYZE_REFERENCES:
            raise SceneCraftError(f"Run {run_id} is not awaiting a building specification")
        if source not in {"astra-agent", "manual"}:
            raise SceneCraftError(f"Unsupported plan source: {source}")
        validate_scene_spec(spec)
        asset_type = read_json(self.run_dir(run_id) / "inputs/project.json").get("asset_type", "building")
        if spec.get("kind", "building") != asset_type:
            raise SceneCraftError(f"Plan kind must match project asset_type {asset_type}")
        run_dir = self.run_dir(run_id)
        snapshot = read_json(run_dir / "inputs/applied-lessons.json")
        applied_ids = [lesson["lesson_id"] for lesson in snapshot["lessons"]] if lessons_applied else []
        if applied_ids:
            LearningStore(self.project).mark_applied(applied_ids, run_id)
        spec_path = self._iteration_spec_path(run_id, 0)
        current_path = run_dir / "plan/current-building-spec.json"
        provenance_path = run_dir / "plan/provenance.json"
        atomic_write_json(spec_path, spec)
        atomic_write_json(current_path, spec)
        atomic_write_json(
            provenance_path,
            {
                "schema_version": 1, "run_id": run_id, "source": source,
                "openai_api_used": False, "lessons_applied": applied_ids, "submitted_at": utc_now(),
            },
        )
        state.transition(Stage.PLAN_GEOMETRY, message="Structured building specification accepted")
        self._record(state, "building_spec_000", spec_path)
        self._record(state, "current_building_spec", current_path)
        self._record(state, "plan_provenance", provenance_path)
        state.transition(Stage.BUILD_GEOMETRY, message="Ready for trusted Blender build")
        state.save(self.state_path(run_id))
        self.prepare_build_job(run_id)
        state = self.load(run_id)
        state.wait("Blender build job prepared")
        state.save(self.state_path(run_id))
        return state

    def accept_repair(self, run_id: str, repair: dict[str, Any], *, source: str = "astra-agent") -> RunState:
        state = self.load(run_id)
        self.verify_inputs(state)
        if state.current_stage != Stage.REPAIR_MODEL:
            raise SceneCraftError(f"Run {run_id} is not awaiting a repair plan")
        if source not in {"astra-agent", "manual"}:
            raise SceneCraftError(f"Unsupported repair source: {source}")
        validate_repair(repair, iteration=state.iteration)
        asset_type = read_json(self.run_dir(run_id) / "inputs/project.json").get("asset_type", "building")
        if repair["building_spec"].get("kind", "building") != asset_type:
            raise SceneCraftError("Repair must preserve the project's asset type")
        next_iteration = state.iteration + 1
        if next_iteration > state.max_iterations:
            raise SceneCraftError("Repair iteration limit exceeded")
        run_dir = self.run_dir(run_id)
        repair_path = run_dir / f"repairs/repair-{next_iteration:03d}.json"
        spec_path = self._iteration_spec_path(run_id, next_iteration)
        current_path = run_dir / "plan/current-building-spec.json"
        provenance_path = run_dir / f"repairs/provenance-{next_iteration:03d}.json"
        atomic_write_json(repair_path, repair)
        atomic_write_json(spec_path, repair["building_spec"])
        atomic_write_json(current_path, repair["building_spec"])
        atomic_write_json(
            provenance_path,
            {"schema_version": 1, "run_id": run_id, "iteration": next_iteration, "source": source, "openai_api_used": False, "submitted_at": utc_now()},
        )
        state.transition(Stage.BUILD_GEOMETRY, message=f"Repair {next_iteration} accepted")
        self._record(state, f"repair_{next_iteration:03d}", repair_path)
        self._record(state, f"building_spec_{next_iteration:03d}", spec_path)
        self._record(state, "current_building_spec", current_path)
        self._record(state, f"repair_provenance_{next_iteration:03d}", provenance_path)
        state.save(self.state_path(run_id))
        self.prepare_build_job(run_id)
        state = self.load(run_id)
        state.wait("Rebuild job prepared from the validated repair")
        state.save(self.state_path(run_id))
        return state

    def prepare_build_job(self, run_id: str) -> Path:
        state = self.load(run_id)
        if state.current_stage != Stage.BUILD_GEOMETRY:
            raise SceneCraftError(f"Run {run_id} is not ready to build")
        iteration = state.iteration
        run_dir = self.run_dir(run_id)
        job_dir = run_dir / f"jobs/iteration-{iteration:03d}/build"
        output_dir = run_dir / f"iterations/{iteration:03d}"
        job_path = job_dir / "job.json"
        manifest = read_json(run_dir / "inputs/reference-manifest.json")
        reference = next(item for item in manifest["references"] if item["role"] == "primary")
        scale = 640 / max(reference["width"], reference["height"])
        render_width = max(64, round(reference["width"] * scale))
        render_height = max(64, round(reference["height"] * scale))
        request = JobRequest(
            job_id=f"{run_id}-build-{iteration:03d}",
            operation="build_scene",
            workspace_root=str(self.project.root),
            inputs={"building_spec": str(self._iteration_spec_path(run_id, iteration))},
            outputs={
                "blend": str(output_dir / "scene.blend"),
                "glb": str(output_dir / "scene.glb"),
                "preview": str(output_dir / "render.png"),
                "scene_manifest": str(output_dir / "scene-manifest.json"),
                "result": str(job_dir / "result.json"),
            },
            settings={"render_width": render_width, "render_height": render_height},
        )
        spec = read_json(self._iteration_spec_path(run_id, iteration))
        if spec.get("kind") in {"object", "positive-master"}:
            request = JobRequest(
                job_id=request.job_id, operation="build_object", workspace_root=request.workspace_root,
                inputs=request.inputs, settings=request.settings,
                outputs={**request.outputs, "stl": str(output_dir / "master-mm.stl"), "geometry_report": str(output_dir / "geometry-report.json"), **{f"inspection_{view}": str(output_dir / f"inspection-{view}.png") for view in ("back", "side", "top")}},
            )
        request.save(job_path)
        self._record(state, f"build_job_{iteration:03d}", job_path)
        state.save(self.state_path(run_id))
        return job_path

    def execute_build(self, run_id: str, worker: BlenderWorker) -> RunState:
        state = self.load(run_id)
        if state.current_stage != Stage.BUILD_GEOMETRY:
            raise SceneCraftError(f"Run {run_id} is not ready to build")
        iteration = state.iteration
        state.status = RunStatus.RUNNING
        state.save(self.state_path(run_id))
        run_dir = self.run_dir(run_id)
        job_dir = run_dir / f"jobs/iteration-{iteration:03d}/build"
        job_path = job_dir / "job.json"
        result_path = job_dir / "result.json"
        log_path = job_dir / "blender.log"
        try:
            self.verify_inputs(state)
            self._verify_state_artifact(state, f"building_spec_{iteration:03d}")
            self._verify_state_artifact(state, f"build_job_{iteration:03d}")
            result = worker.run(job_path, log_path)
            for artifact in result.artifacts:
                self._record(state, f"{artifact['name']}_{iteration:03d}", Path(artifact["path"]))
            self._record(state, f"build_result_{iteration:03d}", result_path)
            self._record(state, f"build_log_{iteration:03d}", log_path)
            state.transition(Stage.RENDER_EVIDENCE, message=f"Iteration {iteration} rendered")
            state.transition(Stage.EVALUATE_FIDELITY, message=f"Evaluating iteration {iteration}")
            state.save(self.state_path(run_id))
            return self.execute_evaluation(run_id)
        except Exception as exc:
            state = self.load(run_id)
            for name, path in ((f"build_result_{iteration:03d}", result_path), (f"build_log_{iteration:03d}", log_path)):
                if path.is_file():
                    self._record(state, name, path)
            state.fail(str(exc))
            state.save(self.state_path(run_id))
            raise

    def verify_inputs(self, state: RunState) -> None:
        self._verify_state_artifact(state, "frozen_project")
        manifest_path = self._verify_state_artifact(state, "frozen_references")
        self._verify_state_artifact(state, "analysis_request")
        self._verify_state_artifact(state, "applied_lessons")
        for reference in read_json(manifest_path)["references"]:
            path = resolve_inside(self.project.root, self.project.root / reference["file"])
            if not path.is_file() or sha256_file(path) != reference["sha256"]:
                raise SceneCraftError(f"Reference failed immutability check: {reference['file']}")

    def execute_evaluation(self, run_id: str) -> RunState:
        state = self.load(run_id)
        if state.current_stage != Stage.EVALUATE_FIDELITY:
            raise SceneCraftError("Run is not ready to evaluate")
        try:
            self.verify_inputs(state)
            for name in ("blend", "glb", "preview", "scene_manifest", "build_result"):
                self._verify_state_artifact(state, f"{name}_{state.iteration:03d}")
            key = f"evaluation_{state.iteration:03d}"
            if key in state.artifacts:
                evaluation = read_json(self._verify_state_artifact(state, key))
            else:
                result = JobResult.load(self._verify_state_artifact(state, f"build_result_{state.iteration:03d}"))
                evaluation = self._evaluate(run_id, result)
                state = self.load(run_id)
            if evaluation["visual_review"] is not None:
                return self._finish_evaluation(run_id, evaluation)
            stored_review = self.run_dir(run_id) / f"iterations/{state.iteration:03d}/visual-review.json"
            if stored_review.is_file():
                return self.accept_visual_review(run_id, read_json(stored_review))
            if not evaluation["metrics_passed"]:
                return self._finish_evaluation(run_id, evaluation)
            request_path = self.run_dir(run_id) / f"iterations/{state.iteration:03d}/visual-review-request.json"
            if f"visual_request_{state.iteration:03d}" not in state.artifacts:
                spec = read_json(self._verify_state_artifact(state, f"building_spec_{state.iteration:03d}"))
                features = ["overall-shape", "reference-feature-completeness", "proportions", "surface-details"]
                features += [item["id"] for group in ("volumes", "openings", "elements", "objects") for item in spec.get(group, [])]
                features += spec.get("required_features", [])
                if spec.get("kind") == "positive-master":
                    features += ["master-scale-confirmed", "master-minimum-features", "master-undercuts-and-release", "master-surface-and-printability"]
                evidence_keys = ["frozen_references", f"building_spec_{state.iteration:03d}", f"preview_{state.iteration:03d}", key]
                if spec.get("kind") in {"object", "positive-master"}:
                    evidence_keys += [f"{name}_{state.iteration:03d}" for name in ("geometry_report", "stl", "inspection_back", "inspection_side", "inspection_top")]
                for evidence_key in evidence_keys:
                    self._verify_state_artifact(state, evidence_key)
                atomic_write_json(request_path, {
                    "schema_version": 1, "run_id": run_id, "iteration": state.iteration,
                    "evidence": {name: state.artifacts[name] for name in evidence_keys},
                    "required_features": sorted(set(features)),
                    "instructions": "Inspect the actual reference, render and comparison. Check missing reference features even when absent from the plan. Return visual-review.schema.json; passing metrics alone is insufficient.",
                })
                self._record(state, f"visual_request_{state.iteration:03d}", request_path)
            state.last_error = None
            state.wait("Metrics passed; independent visual inspection of reference and render is required")
            state.save(self.state_path(run_id))
            return state
        except Exception as exc:
            state = self.load(run_id)
            state.fail(str(exc))
            state.save(self.state_path(run_id))
            raise

    def accept_visual_review(self, run_id: str, review: dict[str, Any]) -> RunState:
        from .review import validate_visual_review

        state = self.load(run_id)
        if state.current_stage != Stage.EVALUATE_FIDELITY:
            raise SceneCraftError("Run is not awaiting visual review")
        self.verify_inputs(state)
        request_path = self._verify_state_artifact(state, f"visual_request_{state.iteration:03d}")
        request = read_json(request_path)
        for key, artifact in request["evidence"].items():
            self._verify_state_artifact(state, key)
            if state.artifacts[key] != artifact:
                raise SceneCraftError("Visual review evidence changed")
        validate_visual_review(review, request, sha256_file(request_path))
        iteration_dir = self.run_dir(run_id) / f"iterations/{state.iteration:03d}"
        review_path = iteration_dir / "visual-review.json"
        if review_path.exists():
            if read_json(review_path) != review:
                raise SceneCraftError("A different review already exists for this iteration")
        else:
            atomic_write_json(review_path, review)
        self._record(state, f"visual_review_{state.iteration:03d}", review_path)
        evaluation_path = self._verify_state_artifact(state, f"evaluation_{state.iteration:03d}")
        evaluation = read_json(evaluation_path)
        metrics_path = iteration_dir / "metrics-evaluation.json"
        if not metrics_path.exists():
            shutil.copyfile(evaluation_path, metrics_path)
        self._record(state, f"metrics_evaluation_{state.iteration:03d}", metrics_path)
        evaluation["visual_review"] = review
        evaluation["accepted"] = evaluation["metrics_passed"] and review["verdict"] == "pass"
        reviewed_path = iteration_dir / "reviewed-evaluation.json"
        if reviewed_path.exists():
            if read_json(reviewed_path) != evaluation:
                raise SceneCraftError("Existing reviewed evaluation differs; evidence is preserved")
        else:
            atomic_write_json(reviewed_path, evaluation)
        self._record(state, f"evaluation_{state.iteration:03d}", reviewed_path)
        state.save(self.state_path(run_id))
        return self._finish_evaluation(run_id, evaluation)

    def _finish_evaluation(self, run_id: str, evaluation: dict[str, Any]) -> RunState:
        state = self.load(run_id)
        if evaluation["accepted"]:
            path = self._verify_state_artifact(state, f"evaluation_{state.iteration:03d}")
            self._record(state, "accepted_evaluation", path)
            state.transition(Stage.PACKAGE_DELIVERABLE, message="Metric and visual acceptance gates passed")
            state.save(self.state_path(run_id))
            return self.execute_package(run_id)
        if state.iteration >= state.max_iterations:
            summary_path = self.run_dir(run_id) / "evidence/best-evaluation.json"
            if not summary_path.exists():
                atomic_write_json(summary_path, self._best_evaluation_summary(run_id))
            self._record(state, "best_evaluation", summary_path)
            state.fail("Acceptance thresholds were not met before the repair limit; retrospective is available")
            LearningStore(self.project).initialize_report(run_id)
        else:
            state.transition(Stage.REPAIR_MODEL, message=f"Iteration {state.iteration} needs repair")
            request_path = self._write_repair_request(run_id, evaluation)
            self._record(state, f"repair_request_{state.iteration:03d}", request_path)
            state.wait("Awaiting a schema-constrained repair from the active Astra/Codex agent")
        state.save(self.state_path(run_id))
        return state

    def record_learning(
        self,
        run_id: str,
        *,
        before_iteration: int,
        after_iteration: int,
        action_key: str,
        stage: str,
        trigger: str,
        learning: str,
        recommended_action: str,
        confidence: float,
        workflow_scope: list[str] | None = None,
        memory_scope: str = "project",
    ) -> dict[str, Any]:
        state = self.load(run_id)
        if state.current_stage != Stage.LEARN_FROM_RUN and state.status != RunStatus.FAILED:
            raise SceneCraftError("Lessons require an accepted package or a failed run")
        before_path, before = self._verified_evaluation(state, before_iteration)
        after_path, after = self._verified_evaluation(state, after_iteration)
        lesson = LearningStore(self.project).record_improvement(
            run_id=run_id,
            action_key=action_key,
            stage=stage,
            trigger=trigger,
            learning=learning,
            recommended_action=recommended_action,
            before_evaluation=before,
            after_evaluation=after,
            confidence=confidence,
            artifact_paths=[
                before_path.relative_to(self.project.root).as_posix(),
                after_path.relative_to(self.project.root).as_posix(),
            ],
            workflow_scope=workflow_scope,
            memory_scope=memory_scope,
        )
        report_path = LearningStore(self.project).report_path(run_id)
        self._record(state, "learning_report", report_path)
        state.save(self.state_path(run_id))
        return lesson

    def complete_learning(self, run_id: str, *, no_lessons_reason: str | None = None) -> RunState:
        state = self.load(run_id)
        if state.status == RunStatus.FAILED:
            report = LearningStore(self.project).finalize_report(run_id, no_lessons_reason=no_lessons_reason)
            self._record(state, "learning_report", report)
            state.save(self.state_path(run_id))
            return state
        if state.current_stage != Stage.LEARN_FROM_RUN:
            raise SceneCraftError(f"Run {run_id} is not in the learning phase")
        if "accepted_evaluation" not in state.artifacts or "deliverable_manifest" not in state.artifacts:
            raise SceneCraftError("Accepted evaluation and packaged deliverable are required")
        self._verify_state_artifact(state, "accepted_evaluation")
        self.verify_inputs(state)
        manifest_path = self._verify_state_artifact(state, "deliverable_manifest")
        self._verify_deliverable(state, manifest_path)
        store = LearningStore(self.project)
        report_path = store.finalize_report(run_id, no_lessons_reason=no_lessons_reason)
        self._record(state, "learning_report", report_path)
        state.transition(Stage.COMPLETE, message="Evidence-backed learning captured; run complete")
        state.save(self.state_path(run_id))
        return state

    def execute_package(self, run_id: str) -> RunState:
        state = self.load(run_id)
        if state.current_stage != Stage.PACKAGE_DELIVERABLE:
            raise SceneCraftError(f"Run {run_id} is not ready to package")
        state.status = RunStatus.RUNNING
        state.save(self.state_path(run_id))
        try:
            self._package(run_id)
            state = self.load(run_id)
            state.transition(Stage.LEARN_FROM_RUN, message="Deliverable packaged; retrospective required")
            LearningStore(self.project).initialize_report(run_id)
            state.wait("Record reusable lessons, then complete the learning phase")
            state.save(self.state_path(run_id))
            return state
        except Exception as exc:
            state = self.load(run_id)
            state.fail(str(exc))
            state.save(self.state_path(run_id))
            raise

    def _evaluate(self, run_id: str, result: JobResult) -> dict[str, Any]:
        state = self.load(run_id)
        self.verify_inputs(state)
        run_dir = self.run_dir(run_id)
        manifest = read_json(run_dir / "inputs/reference-manifest.json")
        reference = next(item for item in manifest["references"] if item["role"] == "primary")
        iteration_dir = run_dir / f"iterations/{state.iteration:03d}"
        evaluation_path = iteration_dir / "evaluation.json"
        comparison_path = iteration_dir / "comparison.png"
        partial = [path for path in (evaluation_path, comparison_path) if path.exists()]
        if partial:
            archive = iteration_dir / "evaluation-attempts" / uuid.uuid4().hex
            archive.mkdir(parents=True)
            for path in partial:
                path.replace(archive / path.name)
        render_path = iteration_dir / "render.png"
        hard_checks = {
            "blend_exists": ((iteration_dir / "scene.blend").is_file(), "Native Blender scene exists"),
            "glb_exists": ((iteration_dir / "scene.glb").is_file(), "GLB interchange export exists"),
            "render_exists": (render_path.is_file(), "Hero render exists"),
            "scene_has_geometry": (int(result.metrics.get("mesh_object_count", 0)) > 0, "Scene contains mesh objects"),
            "camera_locked": (bool(result.metrics.get("camera_locked", False)), "Hero camera came from the accepted spec"),
        }
        spec = read_json(self._iteration_spec_path(run_id, state.iteration))
        if spec.get("kind") == "positive-master":
            report_path = self._verify_state_artifact(state, f"geometry_report_{state.iteration:03d}")
            report = read_json(report_path)
            hard_checks["master_geometry"] = (report["passed"] is True, "Master has one closed component, positive volume, no detected intersections, and declared dimensions")
        evaluation = evaluate_hero_view(
            reference_path=self.project.root / reference["file"],
            render_path=render_path,
            evaluation_path=evaluation_path,
            comparison_path=comparison_path,
            reference_id=reference["id"],
            reference_view=reference["view"],
            iteration=state.iteration,
            thresholds=read_json(run_dir / "inputs/project.json")["acceptance"],
            hard_checks=hard_checks,
        )
        self._record(state, f"evaluation_{state.iteration:03d}", evaluation_path)
        self._record(state, f"comparison_{state.iteration:03d}", comparison_path)
        if evaluation["accepted"]:
            self._record(state, "accepted_evaluation", evaluation_path)
        state.save(self.state_path(run_id))
        return evaluation

    def _write_repair_request(self, run_id: str, evaluation: dict[str, Any]) -> Path:
        state = self.load(run_id)
        path = self.run_dir(run_id) / f"repairs/request-{state.iteration:03d}.json"
        atomic_write_json(
            path,
            {
                "schema_version": 1,
                "run_id": run_id,
                "iteration": state.iteration,
                "evaluation": evaluation,
                "current_spec": str(self._iteration_spec_path(run_id, state.iteration)),
                "expected_output_schema": "schemas/repair.schema.json",
                "instructions": [
                    "Inspect the reference, render, comparison, evaluation, and current spec.",
                    "Prioritize camera, silhouette, large voids, openings, materials, then small details.",
                    "Return a complete revised building_spec and a bounded list of attributable changes.",
                    "Do not return executable code.",
                ],
            },
        )
        return path

    def _package(self, run_id: str) -> None:
        state = self.load(run_id)
        self.verify_inputs(state)
        for name in ("blend", "glb", "preview", "scene_manifest", "evaluation", "comparison", "building_spec", "visual_review"):
            self._verify_state_artifact(state, f"{name}_{state.iteration:03d}")
        if state.current_stage != Stage.PACKAGE_DELIVERABLE:
            raise SceneCraftError("Run is not ready to package")
        run_dir = self.run_dir(run_id)
        iteration_dir = run_dir / f"iterations/{state.iteration:03d}"
        destination = self.project.root / "deliverables" / run_id
        if destination.exists():
            manifest_path = destination / "deliverable-manifest.json"
            if manifest_path.is_file():
                self._verify_deliverable(state, manifest_path)
                self._record(state, "deliverable_manifest", manifest_path)
                state.save(self.state_path(run_id))
                return
            raise SceneCraftError(f"Incomplete deliverable blocks packaging: {destination}")
        staging = self.project.root / "deliverables" / f".{run_id}.partial-{uuid.uuid4().hex[:8]}"
        staging.mkdir(parents=True)
        files = {
            "scene.blend": iteration_dir / "scene.blend",
            "scene.glb": iteration_dir / "scene.glb",
            "hero-render.png": iteration_dir / "render.png",
            "comparison.png": iteration_dir / "comparison.png",
            "scene-manifest.json": iteration_dir / "scene-manifest.json",
            "acceptance-evaluation.json": self._verify_state_artifact(state, "accepted_evaluation"),
            "building-spec.json": self._iteration_spec_path(run_id, state.iteration),
            "reference-manifest.json": run_dir / "inputs/reference-manifest.json",
            "plan-provenance.json": run_dir / "plan/provenance.json",
            "visual-review.json": iteration_dir / "visual-review.json",
        }
        spec = read_json(self._iteration_spec_path(run_id, state.iteration))
        if spec.get("kind") in {"object", "positive-master"}:
            for name in ("stl", "geometry_report", "inspection_back", "inspection_side", "inspection_top"):
                self._verify_state_artifact(state, f"{name}_{state.iteration:03d}")
            files["master-mm.stl"] = iteration_dir / "master-mm.stl"
            files["geometry-report.json"] = iteration_dir / "geometry-report.json"
            for view in ("back", "side", "top"):
                files[f"inspection-{view}.png"] = iteration_dir / f"inspection-{view}.png"
        manifest_files = []
        for name, source in files.items():
            if not source.is_file():
                raise SceneCraftError(f"Cannot package missing artifact: {source}")
            target = staging / name
            shutil.copyfile(source, target)
            manifest_files.append({"name": name, "sha256": sha256_file(target)})
        spec = read_json(self._iteration_spec_path(run_id, state.iteration))
        history = staging / "evaluation-history"
        history.mkdir()
        for iteration in range(state.iteration + 1):
            source_dir = run_dir / f"iterations/{iteration:03d}"
            for source_name in ("render.png", "comparison.png", "evaluation.json"):
                source = source_dir / source_name
                if source_name == "evaluation.json" and f"evaluation_{iteration:03d}" in state.artifacts:
                    source = self._verify_state_artifact(state, f"evaluation_{iteration:03d}")
                if source.is_file():
                    name = f"iteration-{iteration:03d}-{source_name}"
                    target = history / name
                    shutil.copyfile(source, target)
                    manifest_files.append(
                        {"name": f"evaluation-history/{name}", "sha256": sha256_file(target)}
                    )
        repairs = run_dir / "repairs"
        if repairs.is_dir():
            repair_history = staging / "repair-history"
            for source in sorted(path for path in repairs.iterdir() if path.is_file()):
                repair_history.mkdir(exist_ok=True)
                target = repair_history / source.name
                shutil.copyfile(source, target)
                manifest_files.append(
                    {"name": f"repair-history/{source.name}", "sha256": sha256_file(target)}
                )
        uncertainty_path = staging / "uncertainty-report.json"
        atomic_write_json(
            uncertainty_path,
            {
                "schema_version": 1,
                "run_id": run_id,
                "mode": "hero-view",
                "limitations": ["Only the declared hero view is acceptance-tested; unseen geometry remains unconstrained."],
                "uncertainties": spec["uncertainties"],
            },
        )
        manifest_files.append({"name": uncertainty_path.name, "sha256": sha256_file(uncertainty_path)})
        manifest_path = staging / "deliverable-manifest.json"
        atomic_write_json(
            manifest_path,
            {"schema_version": 1, "run_id": run_id, "iteration": state.iteration, "created_at": utc_now(), "files": sorted(manifest_files, key=lambda item: item["name"])},
        )
        self._verify_deliverable(state, manifest_path)
        staging.replace(destination)
        manifest_path = destination / "deliverable-manifest.json"
        self._record(state, "deliverable_manifest", manifest_path)
        state.save(self.state_path(run_id))

    def _verify_deliverable(self, state: RunState, manifest_path: Path) -> None:
        manifest = read_json(manifest_path)
        if (
            set(manifest) != {"schema_version", "run_id", "iteration", "created_at", "files"}
            or manifest.get("schema_version") != 1
            or manifest.get("run_id") != state.run_id
            or manifest.get("iteration") != state.iteration
            or not isinstance(manifest.get("files"), list)
        ):
            raise SceneCraftError(f"Invalid deliverable manifest: {manifest_path}")
        required = {
            "scene.blend",
            "scene.glb",
            "hero-render.png",
            "comparison.png",
            "scene-manifest.json",
            "acceptance-evaluation.json",
            "building-spec.json",
            "reference-manifest.json",
            "plan-provenance.json",
            "uncertainty-report.json",
            "visual-review.json",
        }
        config = read_json(self.run_dir(state.run_id) / "inputs/project.json")
        if config.get("asset_type") in {"object", "positive-master"}:
            required |= {"master-mm.stl", "geometry-report.json", "inspection-back.png", "inspection-side.png", "inspection-top.png"}
        names: set[str] = set()
        root = manifest_path.parent.resolve()
        for index, item in enumerate(manifest["files"]):
            if (
                not isinstance(item, dict)
                or set(item) != {"name", "sha256"}
                or not isinstance(item.get("name"), str)
                or not item["name"]
                or item["name"] in names
                or not isinstance(item.get("sha256"), str)
                or re.fullmatch(r"[a-f0-9]{64}", item["sha256"]) is None
            ):
                raise SceneCraftError(f"Invalid deliverable entry at index {index}")
            names.add(item["name"])
            try:
                path = resolve_inside(root, root / item["name"])
            except ValueError as exc:
                raise SceneCraftError(str(exc)) from exc
            if not path.is_file() or sha256_file(path) != item["sha256"]:
                raise SceneCraftError(f"Deliverable failed integrity check: {path}")
        missing = sorted(required - names)
        if missing:
            raise SceneCraftError(f"Deliverable is missing required files: {', '.join(missing)}")
        evaluation = read_json(root / "acceptance-evaluation.json")
        if evaluation.get("schema_version") != 3 or evaluation.get("accepted") is not True or not evaluation.get("visual_review"):
            raise SceneCraftError("Packaged evaluation is not an accepted SceneCraft evaluation")

    def _verified_evaluation(self, state: RunState, iteration: int) -> tuple[Path, dict[str, Any]]:
        if isinstance(iteration, bool) or not isinstance(iteration, int) or iteration < 0:
            raise ContractError("Evaluation iteration must be a non-negative integer")
        key = f"evaluation_{iteration:03d}"
        artifact = state.artifacts.get(key)
        if not artifact:
            raise SceneCraftError(f"Run has no stored evaluation for iteration {iteration}")
        path = resolve_inside(self.project.root, self.project.root / artifact["path"])
        if not path.is_file() or sha256_file(path) != artifact["sha256"]:
            raise SceneCraftError(f"Evaluation evidence failed integrity check: {path}")
        return path, read_json(path)

    def _best_evaluation_summary(self, run_id: str) -> dict[str, Any]:
        state = self.load(run_id)
        evaluations = []
        for iteration in range(state.iteration + 1):
            try:
                path, value = self._verified_evaluation(state, iteration)
                evaluations.append((float(value["aggregate_score"]), path, value))
            except (SceneCraftError, ValueError, KeyError):
                continue
        if not evaluations:
            raise SceneCraftError("No valid evaluation evidence exists")
        score, path, value = max(evaluations, key=lambda item: item[0])
        return {"schema_version": 2, "run_id": run_id, "iteration": value["iteration"], "aggregate_score": score, "evaluation_path": path.relative_to(self.project.root).as_posix()}

    def _iteration_spec_path(self, run_id: str, iteration: int) -> Path:
        return self.run_dir(run_id) / f"plan/iterations/{iteration:03d}-building-spec.json"

    def _verify_state_artifact(self, state: RunState, name: str) -> Path:
        artifact = state.artifacts.get(name)
        if artifact is None:
            raise SceneCraftError(f"Run is missing required artifact: {name}")
        path = resolve_inside(self.project.root, self.project.root / artifact["path"])
        if not path.is_file() or sha256_file(path) != artifact["sha256"]:
            raise SceneCraftError(f"Artifact failed integrity check: {name}")
        return path

    def _record(self, state: RunState, name: str, path: Path) -> None:
        path = resolve_inside(self.project.root, path)
        if not path.is_file():
            raise SceneCraftError(f"Cannot record missing artifact: {path}")
        state.record_artifact(name, path.relative_to(self.project.root).as_posix(), sha256_file(path))
