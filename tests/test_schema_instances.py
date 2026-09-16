import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from scenecraft.engine import WorkflowEngine
from scenecraft.project import Project
from tests.helpers import SPEC, FakeWorker, approve_visual, make_reference


class SchemaInstanceTests(unittest.TestCase):
    def test_runtime_artifacts_match_public_schemas(self):
        repository = Path(__file__).resolve().parents[1]
        schemas = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in (repository / "schemas").glob("*.schema.json")
        }
        registry = Registry().with_resources(
            (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
        )

        def validate(schema_name: str, value: dict) -> None:
            Draft202012Validator(
                schemas[schema_name], registry=registry, format_checker=FormatChecker()
            ).validate(value)

        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            source = temporary / "hero.png"
            make_reference(source)
            project = Project.create(temporary / "project", "Schema House")
            project.add_reference(source, "primary", "hero")
            spec_path = temporary / "spec.json"
            spec_path.write_text(json.dumps(SPEC), encoding="utf-8")
            engine = WorkflowEngine(project)
            state = engine.start(spec_path)
            run = engine.run_dir(state.run_id)
            validate("project.schema.json", project.config())
            validate("reference-manifest.schema.json", project.references())
            validate("analysis-request.schema.json", json.loads((run / "analysis-request.json").read_text()))
            validate("building-spec.schema.json", SPEC)
            validate("job.schema.json", json.loads((run / "jobs/iteration-000/build/job.json").read_text()))
            state = engine.execute_build(state.run_id, FakeWorker(source))
            state = approve_visual(engine, state.run_id)
            validate("result.schema.json", json.loads((run / "jobs/iteration-000/build/result.json").read_text()))
            validate("evaluation.schema.json", json.loads((run / "iterations/000/evaluation.json").read_text()))
            validate("plan-provenance.schema.json", json.loads((run / "plan/provenance.json").read_text()))
            state = engine.complete_learning(
                state.run_id, no_lessons_reason="No repair was needed in the schema test."
            )
            validate("learning-report.schema.json", json.loads((run / "learning/report.json").read_text()))
            validate("learning-memory.schema.json", json.loads((project.root / ".scenecraft/learning/lessons.json").read_text()))
            validate("run-state.schema.json", state.to_dict())
            validate(
                "repair.schema.json",
                {
                    "schema_version": 2,
                    "based_on_iteration": 0,
                    "changes": [{"target": "camera.lens_mm", "reason": "Improve alignment"}],
                    "building_spec": SPEC,
                },
            )


if __name__ == "__main__":
    unittest.main()
