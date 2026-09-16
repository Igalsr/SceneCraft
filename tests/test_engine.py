import json
import tempfile
import unittest
from pathlib import Path

from scenecraft.engine import WorkflowEngine
from scenecraft.errors import SceneCraftError
from scenecraft.project import Project
from scenecraft.state import RunStatus, Stage
from tests.helpers import SPEC, FakeWorker, approve_visual, make_reference


class EngineTests(unittest.TestCase):
    def _project(self, temporary: Path) -> tuple[Project, Path]:
        source = temporary / "hero.png"
        make_reference(source)
        project = Project.create(temporary / "project", "Test House")
        project.add_reference(source, "primary", "hero")
        return project, source

    def test_agent_native_run_waits_without_calling_an_api(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, _ = self._project(Path(temporary))
            state = WorkflowEngine(project).start()
            request = json.loads(
                (project.root / "runs" / state.run_id / "analysis-request.json").read_text()
            )
            self.assertEqual(state.current_stage, Stage.ANALYZE_REFERENCES)
            self.assertEqual(state.status, RunStatus.WAITING)
            self.assertEqual(request["orchestrator"]["mode"], "codex-agent")
            self.assertFalse(request["orchestrator"]["api_call"])

    def test_accepted_render_packages_and_requires_learning_closeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            project, source = self._project(temporary)
            spec_path = temporary / "spec.json"
            spec_path.write_text(json.dumps(SPEC), encoding="utf-8")
            engine = WorkflowEngine(project)
            state = engine.start(spec_path)
            state = engine.execute_build(state.run_id, FakeWorker(source))
            self.assertEqual(state.current_stage, Stage.EVALUATE_FIDELITY)
            state = approve_visual(engine, state.run_id)
            self.assertEqual(state.current_stage, Stage.LEARN_FROM_RUN)
            self.assertTrue((project.root / "deliverables" / state.run_id / "scene.blend").is_file())
            with self.assertRaises(SceneCraftError):
                engine.complete_learning(state.run_id)
            state = engine.complete_learning(
                state.run_id, no_lessons_reason="The initial plan passed without a repair."
            )
            self.assertEqual(state.current_stage, Stage.COMPLETE)

    def test_rejected_render_requests_repair_and_preserves_iterations(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            project, source = self._project(temporary)
            spec_path = temporary / "spec.json"
            spec_path.write_text(json.dumps(SPEC), encoding="utf-8")
            engine = WorkflowEngine(project)
            worker = FakeWorker(source, first_variant="bad")
            state = engine.start(spec_path)
            state = engine.execute_build(state.run_id, worker)
            self.assertEqual(state.current_stage, Stage.REPAIR_MODEL)
            repair = {
                "schema_version": 2,
                "based_on_iteration": 0,
                "changes": [{"target": "camera.lens_mm", "reason": "Improve hero alignment"}],
                "building_spec": {**SPEC, "camera": {**SPEC["camera"], "lens_mm": 55}},
            }
            engine.accept_repair(state.run_id, repair)
            state = engine.execute_build(state.run_id, worker)
            state = approve_visual(engine, state.run_id)
            self.assertEqual(state.current_stage, Stage.LEARN_FROM_RUN)
            self.assertTrue((engine.run_dir(state.run_id) / "iterations/000/evaluation.json").is_file())
            self.assertTrue((engine.run_dir(state.run_id) / "iterations/001/evaluation.json").is_file())
            repair_history = project.root / "deliverables" / state.run_id / "repair-history"
            self.assertTrue((repair_history / "repair-001.json").is_file())
            self.assertTrue((repair_history / "provenance-001.json").is_file())

    def test_completion_rehashes_every_packaged_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            project, source = self._project(temporary)
            spec_path = temporary / "spec.json"
            spec_path.write_text(json.dumps(SPEC), encoding="utf-8")
            engine = WorkflowEngine(project)
            state = engine.start(spec_path)
            state = engine.execute_build(state.run_id, FakeWorker(source))
            state = approve_visual(engine, state.run_id)
            packaged_scene = project.root / "deliverables" / state.run_id / "scene.blend"
            packaged_scene.write_bytes(b"tampered")
            with self.assertRaises(SceneCraftError):
                engine.complete_learning(
                    state.run_id,
                    no_lessons_reason="The initial plan passed without a repair.",
                )

    def test_run_id_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, _ = self._project(Path(temporary))
            with self.assertRaises(SceneCraftError):
                WorkflowEngine(project).run_dir("../outside")

    def test_non_hero_workflow_cannot_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            source = temporary / "hero.png"
            make_reference(source)
            project = Project.create(temporary / "project", "Test House", "multi-view")
            project.add_reference(source, "primary", "hero")
            with self.assertRaises(SceneCraftError):
                WorkflowEngine(project).start()

    def test_material_reference_cannot_substitute_for_primary_hero(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            source = temporary / "material.png"
            make_reference(source)
            project = Project.create(temporary / "project", "Test House")
            project.add_reference(source, "material", "wall-finish")
            with self.assertRaises(SceneCraftError):
                WorkflowEngine(project).start()


if __name__ == "__main__":
    unittest.main()
