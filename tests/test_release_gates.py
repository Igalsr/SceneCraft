import copy
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scenecraft.cli import _advance, main
from scenecraft.contracts import validate_scene_spec
from scenecraft.engine import WorkflowEngine
from scenecraft.errors import ContractError, SceneCraftError, WorkerError
from scenecraft.learning import LearningStore
from scenecraft.project import Project
from scenecraft.protocol import JobRequest, JobResult
from scenecraft.state import RunState, RunStatus, Stage
from scenecraft.util import atomic_write_json, read_json, sha256_file
from scenecraft.worker import BlenderWorker
from tests.helpers import SPEC, FakeWorker, approve_visual, make_reference, visual_review


def setup_run(tmp_path, *, max_iterations=8):
    source = tmp_path / "source.png"
    make_reference(source)
    project = Project.create(tmp_path / "project", "Regression")
    reference = project.add_reference(source, "primary", "hero")
    config = project.config()
    config["max_iterations"] = max_iterations
    atomic_write_json(project.root / ".scenecraft/project.json", config)
    engine = WorkflowEngine(project)
    state = engine.start()
    state = engine.accept_spec(state.run_id, copy.deepcopy(SPEC), source="manual", lessons_applied=False)
    return source, project, engine, state, reference


def test_metric_pass_does_not_package_and_visual_rejection_repairs(tmp_path):
    source, project, engine, state, _ = setup_run(tmp_path)
    state = engine.execute_build(state.run_id, FakeWorker(source))
    assert state.current_stage == Stage.EVALUATE_FIDELITY
    assert not (project.root / "deliverables" / state.run_id).exists()
    evaluation = read_json(engine.run_dir(state.run_id) / "iterations/000/evaluation.json")
    assert evaluation["metrics_passed"] and not evaluation["accepted"]
    state = engine.accept_visual_review(state.run_id, visual_review(engine, state.run_id, verdict="repair"))
    assert state.current_stage == Stage.REPAIR_MODEL


def test_review_rejects_missing_features_or_stale_evidence(tmp_path):
    source, _, engine, state, _ = setup_run(tmp_path)
    engine.execute_build(state.run_id, FakeWorker(source))
    review = visual_review(engine, state.run_id)
    review["features"].pop()
    with pytest.raises(ContractError, match="omits"):
        engine.accept_visual_review(state.run_id, review)
    review = visual_review(engine, state.run_id)
    review["request_sha256"] = "0" * 64
    with pytest.raises(ContractError, match="stale"):
        engine.accept_visual_review(state.run_id, review)


def test_evaluation_failure_resumes_without_rebuilding(tmp_path):
    source, _, engine, state, _ = setup_run(tmp_path)
    worker = FakeWorker(source)
    with patch.object(engine, "_evaluate", side_effect=OSError("temporary disk error")), pytest.raises(OSError):
        engine.execute_build(state.run_id, worker)
    assert engine.load(state.run_id).current_stage == Stage.EVALUATE_FIDELITY
    state = _advance(engine, state.run_id, None, None, "unused", False)
    assert state.status == RunStatus.WAITING
    assert worker.calls == 1
    assert approve_visual(engine, state.run_id).current_stage == Stage.LEARN_FROM_RUN


def test_visual_review_checkpoint_failure_is_recoverable(tmp_path):
    source, _, engine, state, _ = setup_run(tmp_path)
    engine.execute_build(state.run_id, FakeWorker(source))
    review = visual_review(engine, state.run_id)
    with patch.object(RunState, "save", side_effect=OSError("checkpoint unavailable")), pytest.raises(OSError):
        engine.accept_visual_review(state.run_id, review)
    state = _advance(engine, state.run_id, None, None, "unused", False)
    assert state.current_stage == Stage.LEARN_FROM_RUN
    iteration = engine.run_dir(state.run_id) / "iterations/000"
    assert read_json(iteration / "evaluation.json")["visual_review"] is None
    assert read_json(iteration / "reviewed-evaluation.json")["accepted"] is True


def test_resume_rechecks_reference_digest_without_modifying_reference(tmp_path):
    source, project, engine, state, reference = setup_run(tmp_path)
    reference_path = project.root / reference["file"]
    real_digest = sha256_file
    with patch("scenecraft.engine.sha256_file", side_effect=lambda path: "0" * 64 if Path(path) == reference_path else real_digest(path)), pytest.raises(SceneCraftError, match="immutability"):
        engine.execute_build(state.run_id, FakeWorker(source))
    assert sha256_file(reference_path) == reference["sha256"]


def test_worker_archives_all_previous_outputs_and_emits_timeout_result(tmp_path):
    _, _, engine, state, _ = setup_run(tmp_path)
    job_path = engine.run_dir(state.run_id) / "jobs/iteration-000/build/job.json"
    job = JobRequest.load(job_path)
    log = job_path.parent / "blender.log"
    for name, path in job.outputs.items():
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"previous-{name}".encode())
    log.write_text("previous-log")
    worker = BlenderWorker("unused", timeout_seconds=1)
    with patch.object(worker, "command", return_value=["unused"]), patch("scenecraft.worker.subprocess.run", side_effect=subprocess.TimeoutExpired("unused", 1)), pytest.raises(WorkerError, match="timeout"):
        worker.run(job_path, log)
    archives = list((job_path.parent / "attempts").glob("*"))
    assert len(archives) == 1
    for name, path in job.outputs.items():
        preserved = archives[0] / "workspace" / Path(path).relative_to(engine.project.root)
        assert preserved.read_bytes() == f"previous-{name}".encode()
    assert JobResult.load(Path(job.outputs["result"])).status == "failed"


def test_failed_run_captures_candidate_without_claiming_success(tmp_path):
    source, project, engine, state, _ = setup_run(tmp_path, max_iterations=1)
    worker = FakeWorker(source, first_variant="bad")
    state = engine.execute_build(state.run_id, worker)
    engine.accept_repair(state.run_id, {"schema_version": 2, "based_on_iteration": 0, "changes": [{"target": "camera", "reason": "Attempt alignment"}], "building_spec": SPEC})
    worker.calls = 0
    state = engine.execute_build(state.run_id, worker)
    assert state.status == RunStatus.FAILED
    engine.record_learning(state.run_id, before_iteration=0, after_iteration=1, action_key="unchanged", stage="evaluate_fidelity", trigger="No improvement", learning="This repair did not help", recommended_action="Try another projection", confidence=0.8)
    assert main(["note", str(project.root), state.run_id, "--action-key", "failure", "--learning", "The repair budget ended", "--action", "Calibrate earlier"]) == 0
    assert engine.complete_learning(state.run_id).status == RunStatus.FAILED
    assert LearningStore(project).applicable("hero-view") == []
    assert len(LearningStore(project).catalog(include_candidates=True)) == 2


def test_shared_memory_is_explicit_and_persistent(tmp_path):
    _, project, _, _, _ = setup_run(tmp_path)
    shared = tmp_path / "shared/lessons.json"
    assert main(["configure-memory", str(project.root), str(shared)]) == 0
    assert LearningStore(project).workflow_path == shared
    assert shared.is_file()


def test_unmeasured_notes_have_no_invented_scores_and_cannot_activate(tmp_path):
    _, project, engine, state, _ = setup_run(tmp_path)
    state.fail("The worker could not launch")
    state.save(engine.state_path(state.run_id))
    store = LearningStore(project)
    lesson = store.record_observation(state.run_id, action_key="setup", learning="A native Blender runtime is required", recommended_action="Run doctor first")
    assert lesson["evidence"]["before_score"] is None
    lesson["status"] = "validated"
    assert not store._is_relevant(lesson, "hero-view")
    from jsonschema import Draft202012Validator
    repository = Path(__file__).resolve().parents[1]
    Draft202012Validator(read_json(repository / "schemas/learning-memory.schema.json")).validate(read_json(store.project_path))


def test_shared_measured_lesson_reaches_another_project(tmp_path):
    source, project, engine, state, _ = setup_run(tmp_path)
    worker = FakeWorker(source, first_variant="bad")
    engine.execute_build(state.run_id, worker)
    engine.accept_repair(state.run_id, {"schema_version": 2, "based_on_iteration": 0, "changes": [{"target": "camera", "reason": "Fix alignment"}], "building_spec": SPEC})
    engine.execute_build(state.run_id, worker)
    approve_visual(engine, state.run_id)
    shared = tmp_path / "reviewed-shared-lessons.json"
    main(["configure-memory", str(project.root), str(shared)])
    lesson = engine.record_learning(state.run_id, before_iteration=0, after_iteration=1, action_key="camera", stage="evaluate_fidelity", trigger="Alignment", learning="Camera calibration improved alignment", recommended_action="Calibrate first", confidence=0.9, memory_scope="workflow")
    other = Project.create(tmp_path / "other", "Other")
    other.add_reference(source, "primary", "hero")
    main(["configure-memory", str(other.root), str(shared)])
    other_engine = WorkflowEngine(other)
    other_state = other_engine.start()
    request = read_json(other_engine.run_dir(other_state.run_id) / "analysis-request.json")
    assert request["validated_lessons"][0]["lesson_id"] == lesson["lesson_id"]


def test_nested_project_evidence_is_ignored():
    repository = Path(__file__).resolve().parents[1]
    for path in ("my-building/inputs/references/private.png", "my-building/.scenecraft/learning/lessons.json", "my-building/artifacts/model.stl"):
        assert subprocess.run(["git", "check-ignore", "-q", path], cwd=repository, check=False).returncode == 0


def test_positive_master_contract_and_job(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    spec = read_json(repository / "examples/positive-master/scene-spec.json")
    validate_scene_spec(spec)
    invalid = copy.deepcopy(spec)
    del invalid["manufacturing"]
    with pytest.raises(ContractError):
        validate_scene_spec(invalid)
    invalid = copy.deepcopy(spec)
    invalid["objects"][0]["operation"] = "difference"
    with pytest.raises(ContractError):
        validate_scene_spec(invalid)
    source = tmp_path / "source.png"
    make_reference(source)
    project = Project.create(tmp_path / "master", "Pawn", asset_type="positive-master")
    project.add_reference(source, "primary", "hero")
    engine = WorkflowEngine(project)
    state = engine.start()
    engine.accept_spec(state.run_id, spec, source="manual", lessons_applied=False)
    job = JobRequest.load(engine.run_dir(state.run_id) / "jobs/iteration-000/build/job.json")
    assert job.operation == "build_object"
    assert {"stl", "geometry_report"} <= set(job.outputs)
    assert json.loads((engine.run_dir(state.run_id) / "analysis-request.json").read_text())["expected_output_schema"] == "schemas/scene-spec.schema.json"
