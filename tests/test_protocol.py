import tempfile
import unittest
from pathlib import Path

from scenecraft.errors import ContractError
from scenecraft.protocol import JobRequest


class ProtocolTests(unittest.TestCase):
    def test_job_round_trip_and_path_containment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "job.json"
            request = JobRequest(
                job_id="build-1",
                operation="build_scene",
                workspace_root=str(root),
                inputs={"building_spec": str(root / "spec.json")},
                outputs={
                    "blend": str(root / "scene.blend"),
                    "glb": str(root / "scene.glb"),
                    "preview": str(root / "preview.png"),
                    "scene_manifest": str(root / "manifest.json"),
                    "result": str(root / "result.json"),
                },
            )
            request.save(path)
            self.assertEqual(JobRequest.load(path), request)

            escaped = JobRequest(
                **{**request.__dict__, "outputs": {**request.outputs, "result": str(root.parent / "result.json")}}
            )
            with self.assertRaises(ContractError):
                escaped.validate()


if __name__ == "__main__":
    unittest.main()
