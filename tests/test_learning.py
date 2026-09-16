import json
import tempfile
import unittest
from pathlib import Path

from scenecraft.engine import WorkflowEngine
from scenecraft.learning import LearningStore
from scenecraft.project import Project
from tests.helpers import SPEC, FakeWorker, approve_visual, make_reference


class LearningTests(unittest.TestCase):
    def test_only_stored_evaluations_can_validate_a_lesson(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            source = temporary / "hero.png"
            make_reference(source)
            project = Project.create(temporary / "project", "Learning House")
            project.add_reference(source, "primary", "hero")
            spec_path = temporary / "spec.json"
            spec_path.write_text(json.dumps(SPEC), encoding="utf-8")
            engine = WorkflowEngine(project)
            worker = FakeWorker(source, first_variant="bad")
            state = engine.start(spec_path)
            state = engine.execute_build(state.run_id, worker)
            repair = {
                "schema_version": 2,
                "based_on_iteration": 0,
                "changes": [{"target": "camera", "reason": "Correct the hero projection"}],
                "building_spec": {**SPEC, "camera": {**SPEC["camera"], "lens_mm": 55}},
            }
            engine.accept_repair(state.run_id, repair)
            state = engine.execute_build(state.run_id, worker)
            state = approve_visual(engine, state.run_id)
            lesson = engine.record_learning(
                state.run_id,
                before_iteration=0,
                after_iteration=1,
                action_key="camera.hero-focal-length",
                stage="evaluate_fidelity",
                trigger="The initial hero projection did not align",
                learning="The repaired camera aligned all stored metrics",
                recommended_action="Calibrate the hero camera before facade detail",
                confidence=0.9,
            )
            self.assertEqual(lesson["status"], "validated")
            engine.complete_learning(state.run_id)

            second = engine.start()
            request = json.loads(
                (project.root / "runs" / second.run_id / "analysis-request.json").read_text()
            )
            self.assertEqual(request["validated_lessons"][0]["action_key"], "camera.hero-focal-length")
            engine.accept_spec(second.run_id, SPEC, source="astra-agent", lessons_applied=True)
            active = LearningStore(project).catalog()
            self.assertEqual(active[0]["application_count"], 1)


if __name__ == "__main__":
    unittest.main()
