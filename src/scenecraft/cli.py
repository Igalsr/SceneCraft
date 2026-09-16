from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import WorkflowEngine
from .errors import SceneCraftError
from .project import Project
from .state import Stage
from .worker import BlenderWorker, python_runtime, trusted_runner_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scenecraft",
        description="Reference-image-to-Blender workflow",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create a SceneCraft project")
    init.add_argument("project", type=Path)
    init.add_argument("--name", required=True)
    init.add_argument("--asset-type", choices=["building", "object", "positive-master"], default="object")
    init.add_argument(
        "--workflow",
        choices=["hero-view", "multi-view", "metric"],
        default="hero-view",
    )

    add = sub.add_parser("add-reference", help="Import an immutable reference image")
    add.add_argument("project", type=Path)
    add.add_argument("image", type=Path)
    add.add_argument(
        "--role",
        choices=["primary", "supporting", "material", "scale"],
        default="primary",
    )
    add.add_argument("--view", default="hero")
    add.add_argument("--notes", default="")

    doctor = sub.add_parser("doctor", help="Check local execution prerequisites")
    doctor.add_argument("--blender", default="blender")

    run = sub.add_parser("run", help="Start a new workflow run")
    run.add_argument("project", type=Path)
    run.add_argument(
        "--spec",
        type=Path,
        help="Use a reviewed manual specification and bypass Astra analysis",
    )
    run.add_argument("--blender", default="blender")
    run.add_argument("--dry-run", action="store_true")

    resume = sub.add_parser("resume", help="Resume a checkpointed run")
    resume.add_argument("project", type=Path)
    resume.add_argument("run_id")
    resume.add_argument("--spec", type=Path)
    resume.add_argument("--repair", type=Path)
    resume.add_argument("--review", type=Path, help="Evidence-bound visual review JSON")
    resume.add_argument(
        "--plan-source",
        choices=["astra-agent", "manual"],
        default="astra-agent",
    )
    resume.add_argument("--blender", default="blender")
    resume.add_argument("--dry-run", action="store_true")

    status = sub.add_parser("status", help="Show a run checkpoint")
    status.add_argument("project", type=Path)
    status.add_argument("--run-id")

    learn = sub.add_parser("learn", help="Record an evidence-backed lesson from a run")
    learn.add_argument("project", type=Path)
    learn.add_argument("run_id")
    learn.add_argument("--action-key", required=True)
    learn.add_argument("--stage", required=True, choices=[stage.value for stage in Stage])
    learn.add_argument("--trigger", required=True)
    learn.add_argument("--learning", required=True)
    learn.add_argument("--action", required=True, dest="recommended_action")
    learn.add_argument("--before-iteration", required=True, type=int)
    learn.add_argument("--after-iteration", required=True, type=int)
    learn.add_argument("--confidence", type=float, default=0.8)
    learn.add_argument(
        "--workflow-scope",
        action="append",
        choices=["hero-view", "multi-view", "metric"],
    )
    learn.add_argument("--memory-scope", choices=["project", "workflow"], default="project")

    complete = sub.add_parser("complete", help="Close the required learning phase")
    complete.add_argument("project", type=Path)
    complete.add_argument("run_id")
    complete.add_argument(
        "--no-lessons-reason",
        help="Required when no reusable lesson was recorded",
    )

    lessons = sub.add_parser("lessons", help="List active or candidate workflow lessons")
    lessons.add_argument("project", type=Path)
    lessons.add_argument(
        "--all",
        action="store_true",
        help="Include candidates and deprecated lessons",
    )
    memory = sub.add_parser("configure-memory", help="Select a reviewed shared lesson store for this project")
    memory.add_argument("project", type=Path)
    memory.add_argument("path", type=Path)
    note = sub.add_parser("note", help="Preserve an unmeasured candidate lesson from a completed or failed attempt")
    note.add_argument("project", type=Path)
    note.add_argument("run_id")
    note.add_argument("--action-key", required=True)
    note.add_argument("--learning", required=True)
    note.add_argument("--action", required=True)
    return parser


def _print_state(state) -> None:
    print(json.dumps(state.to_dict(), indent=2, sort_keys=True))


def _advance(
    engine: WorkflowEngine,
    run_id: str,
    spec: Path | None,
    repair: Path | None,
    blender: str,
    dry_run: bool,
    plan_source: str = "manual",
    review: Path | None = None,
):
    state = engine.load(run_id)
    if state.current_stage == Stage.ANALYZE_REFERENCES:
        if spec is not None:
            from .util import read_json

            state = engine.accept_spec(
                run_id,
                read_json(spec),
                source=plan_source,
                lessons_applied=plan_source == "astra-agent",
            )
        else:
            state.wait("Analysis request prepared for the active Astra/Codex agent")
            state.save(engine.state_path(run_id))
            return state
    if state.current_stage == Stage.REPAIR_MODEL:
        if repair is not None:
            from .util import read_json

            state = engine.accept_repair(run_id, read_json(repair), source=plan_source)
        else:
            state.wait("Repair request prepared for the active Astra/Codex agent")
            state.save(engine.state_path(run_id))
            return state
    if state.current_stage == Stage.BUILD_GEOMETRY:
        if f"build_job_{state.iteration:03d}" not in state.artifacts:
            engine.prepare_build_job(run_id)
            state = engine.load(run_id)
        if dry_run:
            state.wait("Dry run complete: trusted Blender job prepared")
            state.save(engine.state_path(run_id))
            return state
        return engine.execute_build(run_id, BlenderWorker(blender))
    if state.current_stage == Stage.PACKAGE_DELIVERABLE:
        return engine.execute_package(run_id)
    if state.current_stage == Stage.EVALUATE_FIDELITY:
        if review is not None:
            from .util import read_json
            return engine.accept_visual_review(run_id, read_json(review))
        return engine.execute_evaluation(run_id)
    return state


def execute(args: argparse.Namespace) -> int:
    if args.command == "init":
        project = Project.create(args.project, args.name, args.workflow, args.asset_type)
        print(project.root)
        return 0
    if args.command == "add-reference":
        project = Project.open(args.project)
        reference = project.add_reference(args.image, args.role, args.view, args.notes)
        print(json.dumps(reference, indent=2))
        return 0
    if args.command == "doctor":
        info = BlenderWorker(args.blender).doctor()
        runner = trusted_runner_path()
        print(
            json.dumps(
                {
                    "python": python_runtime(),
                    "blender": info.__dict__,
                    "trusted_runner": {"path": str(runner), "available": runner.is_file()},
                    "orchestration": {
                        "mode": "codex-agent",
                        "required_model": "gpt-6-astra",
                        "openai_sdk_required": False,
                        "api_key_required": False,
                    },
                },
                indent=2,
            )
        )
        return 0 if info.available else 2

    project = Project.open(args.project)
    engine = WorkflowEngine(project)
    if args.command == "run":
        state = engine.start(args.spec)
        state = _advance(engine, state.run_id, None, None, args.blender, args.dry_run)
        _print_state(state)
        return 0
    if args.command == "resume":
        state = _advance(
            engine,
            args.run_id,
            args.spec,
            args.repair,
            args.blender,
            args.dry_run,
            args.plan_source,
            args.review,
        )
        _print_state(state)
        return 0
    if args.command == "status":
        run_id = args.run_id or engine.latest_run_id()
        if run_id is None:
            raise SceneCraftError("This project has no runs")
        _print_state(engine.load(run_id))
        return 0
    if args.command == "learn":
        lesson = engine.record_learning(
            args.run_id,
            action_key=args.action_key,
            stage=args.stage,
            trigger=args.trigger,
            learning=args.learning,
            recommended_action=args.recommended_action,
            before_iteration=args.before_iteration,
            after_iteration=args.after_iteration,
            confidence=args.confidence,
            workflow_scope=args.workflow_scope,
            memory_scope=args.memory_scope,
        )
        print(json.dumps(lesson, indent=2, sort_keys=True))
        return 0
    if args.command == "complete":
        state = engine.complete_learning(args.run_id, no_lessons_reason=args.no_lessons_reason)
        _print_state(state)
        return 0
    if args.command == "lessons":
        from .learning import LearningStore

        print(json.dumps(LearningStore(project).catalog(include_candidates=args.all), indent=2))
        return 0
    if args.command == "configure-memory":
        from .learning import LearningStore
        from .util import atomic_write_json

        path = args.path.resolve()
        LearningStore.initialize(path)
        LearningStore._load(path)
        atomic_write_json(project.root / ".scenecraft/memory-config.json", {"schema_version": 1, "workflow_memory": str(path)})
        print(path)
        return 0
    if args.command == "note":
        from .learning import LearningStore
        from .state import RunStatus
        state = engine.load(args.run_id)
        if state.current_stage != Stage.LEARN_FROM_RUN and state.status != RunStatus.FAILED:
            raise SceneCraftError("Notes require a failed run or the learning phase")
        print(json.dumps(LearningStore(project).record_observation(args.run_id, action_key=args.action_key, learning=args.learning, recommended_action=args.action), indent=2))
        return 0
    raise SceneCraftError(f"Unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    try:
        return execute(build_parser().parse_args(argv))
    except (SceneCraftError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
