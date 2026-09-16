import tempfile
import unittest
from pathlib import Path

from scenecraft.errors import ContractError
from scenecraft.state import RunState, Stage


class StateTests(unittest.TestCase):
    def test_state_round_trip_and_transition_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            state = RunState(run_id="run-1", project_id="project-1")
            state.transition(Stage.ANALYZE_REFERENCES)
            state.wait("awaiting analysis")
            state.save(path)

            loaded = RunState.load(path)
            self.assertEqual(loaded.current_stage, Stage.ANALYZE_REFERENCES)
            self.assertEqual(loaded.message, "awaiting analysis")
            with self.assertRaises(ContractError):
                loaded.transition(Stage.RENDER_EVIDENCE)

    def test_learning_is_required_before_completion(self):
        state = RunState(
            run_id="run-2",
            project_id="project-1",
            current_stage=Stage.PACKAGE_DELIVERABLE,
        )
        with self.assertRaises(ContractError):
            state.transition(Stage.COMPLETE)
        state.transition(Stage.LEARN_FROM_RUN)
        for name in ("accepted_evaluation", "deliverable_manifest", "learning_report"):
            state.record_artifact(name, f"{name}.json", "0" * 64)
        state.transition(Stage.COMPLETE)
        self.assertEqual(state.current_stage, Stage.COMPLETE)


if __name__ == "__main__":
    unittest.main()
