import json
import os
import tempfile
import unittest
from pathlib import Path

from scenecraft.protocol import JobRequest
from scenecraft.worker import BlenderWorker


@unittest.skipUnless(os.environ.get("SCENECRAFT_BLENDER"), "set SCENECRAFT_BLENDER for a real Blender smoke test")
class BlenderSmokeTests(unittest.TestCase):
    def test_positive_master_exports_closed_geometry_and_mm_stl(self):
        import struct

        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            spec_path = root / "spec.json"
            spec_path.write_text((repository / "examples/positive-master/scene-spec.json").read_text())
            outputs = {name: str(root / path) for name, path in {"blend": "out/master.blend", "glb": "out/master.glb", "preview": "out/render.png", "scene_manifest": "out/scene-manifest.json", "result": "job/result.json", "stl": "out/master-mm.stl", "geometry_report": "out/geometry-report.json"}.items()}
            job_path = root / "job/job.json"
            outputs.update({f"inspection_{view}": str(root / f"out/inspection-{view}.png") for view in ("back", "side", "top")})
            JobRequest(job_id="master-smoke", operation="build_object", workspace_root=str(root), inputs={"building_spec": str(spec_path)}, outputs=outputs, settings={"render_width": 128, "render_height": 128}).save(job_path)
            BlenderWorker(os.environ["SCENECRAFT_BLENDER"], timeout_seconds=300).run(job_path, root / "job/blender.log")
            report = json.loads(Path(outputs["geometry_report"]).read_text())
            from jsonschema import Draft202012Validator
            Draft202012Validator(json.loads((repository / "schemas/geometry-report.schema.json").read_text())).validate(report)
            self.assertTrue(report["passed"], report)
            stl = Path(outputs["stl"]).read_bytes()
            count = struct.unpack_from("<I", stl, 80)[0]
            self.assertEqual(len(stl), 84 + 50 * count)
            vertices = [struct.unpack_from("<12fH", stl, 84 + index * 50)[3:12] for index in range(count)]
            z = [vertex[offset] for vertex in vertices for offset in (2, 5, 8)]
            self.assertAlmostEqual(max(z) - min(z), 81, places=2)
            glb = Path(outputs["glb"]).read_bytes()
            json_length, chunk_type = struct.unpack_from("<II", glb, 12)
            self.assertEqual(chunk_type, 0x4E4F534A)
            gltf = json.loads(glb[20:20 + json_length])
            self.assertEqual(len(gltf["meshes"]), 1, "Source operands must not leak into GLB export")

    def test_packaged_runner_builds_native_interchange_and_render_artifacts(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            spec = root / "spec.json"
            spec.write_text(
                (repository / "examples/minimal-house/building-spec.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            outputs = {
                "blend": str(root / "out/scene.blend"),
                "glb": str(root / "out/scene.glb"),
                "preview": str(root / "out/render.png"),
                "scene_manifest": str(root / "out/scene-manifest.json"),
                "result": str(root / "job/result.json"),
            }
            job_path = root / "job/job.json"
            JobRequest(
                job_id="blender-smoke",
                operation="build_scene",
                workspace_root=str(root),
                inputs={"building_spec": str(spec)},
                outputs=outputs,
                settings={"render_width": 128, "render_height": 128},
            ).save(job_path)
            result = BlenderWorker(os.environ["SCENECRAFT_BLENDER"], timeout_seconds=300).run(
                job_path, root / "job/blender.log"
            )
            self.assertEqual(result.status, "succeeded")
            self.assertEqual(
                {item["name"] for item in result.artifacts},
                {"blend", "glb", "preview", "scene_manifest"},
            )
            manifest = json.loads(Path(outputs["scene_manifest"]).read_text(encoding="utf-8"))
            self.assertGreater(len(manifest["objects"]), 0)


if __name__ == "__main__":
    unittest.main()
