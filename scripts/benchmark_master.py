"""Run a reproducible Blender master benchmark, stopping for real visual review.

The reference is rendered from a known repository fixture. This tests plumbing,
geometry, rejection and repair; it is not evidence of arbitrary-image reconstruction.
"""
import argparse
import copy
from pathlib import Path

from scenecraft.engine import WorkflowEngine
from scenecraft.project import Project
from scenecraft.protocol import JobRequest
from scenecraft.state import Stage
from scenecraft.util import atomic_write_json, read_json
from scenecraft.worker import BlenderWorker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--blender", required=True)
    args = parser.parse_args()
    root = args.directory.resolve()
    if root.exists():
        parser.error("Use a new benchmark directory; existing evidence is never replaced")
    root.mkdir(parents=True)
    spec = read_json(Path(__file__).resolve().parents[1] / "examples/positive-master/scene-spec.json")
    seed = root / "reference-source"
    spec_path = seed / "scene-spec.json"
    atomic_write_json(spec_path, spec)
    job_path = seed / "job.json"
    outputs = {"blend": "scene.blend", "glb": "scene.glb", "preview": "reference.png", "scene_manifest": "scene-manifest.json", "result": "result.json", "stl": "master-mm.stl", "geometry_report": "geometry-report.json"}
    outputs.update({f"inspection_{view}": f"inspection-{view}.png" for view in ("back", "side", "top")})
    JobRequest(job_id="master-benchmark-reference", operation="build_object", workspace_root=str(root), inputs={"building_spec": str(spec_path)}, outputs={name: str(seed / path) for name, path in outputs.items()}, settings={"render_width": 640, "render_height": 640}).save(job_path)
    worker = BlenderWorker(args.blender, timeout_seconds=300)
    worker.run(job_path, seed / "blender.log")
    project = Project.create(root / "project", "Master benchmark", asset_type="positive-master")
    project.add_reference(seed / "reference.png", "primary", "hero", "Generated from the repository's 0BSD positive-master fixture")
    engine = WorkflowEngine(project)
    state = engine.start()
    incorrect = copy.deepcopy(spec)
    incorrect["objects"].pop()  # Deliberately omit the head.
    engine.accept_spec(state.run_id, incorrect, source="manual", lessons_applied=False)
    state = engine.execute_build(state.run_id, worker)
    if state.current_stage != Stage.REPAIR_MODEL:
        raise RuntimeError(f"Missing-head fixture unexpectedly reached {state.current_stage}")
    repair = {"schema_version": 2, "based_on_iteration": 0, "changes": [{"target": "objects.head", "reason": "Restore the missing reference head and target height"}], "building_spec": spec}
    engine.accept_repair(state.run_id, repair, source="manual")
    state = engine.execute_build(state.run_id, worker)
    if state.current_stage != Stage.EVALUATE_FIDELITY:
        raise RuntimeError(f"Correct fixture did not reach visual review: {state.to_dict()}")
    atomic_write_json(root / "benchmark.json", {"schema_version": 1, "project": str(project.root), "run_id": state.run_id, "status": "awaiting_visual_review", "limitations": "Known-spec synthetic benchmark, not independent reference reconstruction"})
    print(root / "benchmark.json")


if __name__ == "__main__":
    main()
