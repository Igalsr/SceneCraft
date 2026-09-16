import json
import sys
import tempfile
import unittest
from pathlib import Path

from scenecraft.errors import WorkerError
from scenecraft.protocol import JobRequest, JobResult
from scenecraft.worker import BlenderWorker
from tests.helpers import SPEC


class ScriptWorker(BlenderWorker):
    def __init__(self, script: Path, result_path: Path):
        super().__init__(sys.executable)
        self.script = script
        self.result_path = result_path

    def command(self, job_path: Path) -> list[str]:
        return [sys.executable, str(self.script), str(self.result_path)]


class WorkerTests(unittest.TestCase):
    def test_mismatched_result_identity_is_rejected_and_stale_result_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job_path = root / "jobs/job.json"
            result_path = root / "jobs/result.json"
            outputs = {
                "blend": str(root / "out/scene.blend"),
                "glb": str(root / "out/scene.glb"),
                "preview": str(root / "out/preview.png"),
                "scene_manifest": str(root / "out/manifest.json"),
                "result": str(result_path),
            }
            (root / "spec.json").write_text(json.dumps(SPEC), encoding="utf-8")
            JobRequest(
                job_id="new-job",
                operation="build_scene",
                workspace_root=str(root),
                inputs={"building_spec": str(root / "spec.json")},
                outputs=outputs,
            ).save(job_path)
            JobResult(job_id="stale-job", status="failed", error="old").save(result_path)
            script = root / "write_result.py"
            script.write_text(
                "import json,sys\n"
                "from pathlib import Path\n"
                "Path(sys.argv[1]).write_text(json.dumps({"
                "'schema_version':2,'job_id':'wrong-job','status':'succeeded',"
                "'artifacts':[],'metrics':{},'warnings':[],'error':None}))\n",
                encoding="utf-8",
            )
            with self.assertRaises(WorkerError):
                ScriptWorker(script, result_path).run(job_path, root / "jobs/worker.log")
            stale = list(result_path.parent.glob("attempts/*/workspace/jobs/result.json"))
            self.assertEqual(len(stale), 1)
            self.assertEqual(json.loads(stale[0].read_text())["job_id"], "stale-job")


if __name__ == "__main__":
    unittest.main()
