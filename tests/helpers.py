from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from scenecraft.protocol import JobRequest, JobResult
from scenecraft.util import atomic_write_json, read_json, sha256_file

SPEC = {
    "schema_version": 1,
    "name": "Test House",
    "units": "meters",
    "envelope": {"width": 10.0, "depth": 7.0, "height": 5.6},
    "floors": 2,
    "wall_thickness": 0.2,
    "camera": {"position": [12, -14, 8], "target": [0, 0, 2.8], "lens_mm": 50},
    "materials": {
        "wall_rgb": [0.7, 0.7, 0.7],
        "roof_rgb": [0.1, 0.1, 0.1],
        "glass_rgb": [0.2, 0.3, 0.4],
        "accent_rgb": [0.08, 0.08, 0.08],
    },
    "openings": [
        {"id": "hero-window", "kind": "window", "facade": "front", "center": [0, 3], "width": 3, "height": 1.8}
    ],
    "elements": [],
    "volumes": [],
    "roof": {"type": "flat", "overhang": 0.2},
    "uncertainties": [],
}


def visual_review(engine, run_id, *, verdict="pass"):
    state = engine.load(run_id)
    request_path = engine.run_dir(run_id) / f"iterations/{state.iteration:03d}/visual-review-request.json"
    request = read_json(request_path)
    return {
        "schema_version": 1, "run_id": run_id, "iteration": state.iteration,
        "request_sha256": sha256_file(request_path), "reviewer": "human", "verdict": verdict,
        "features": [{"id": feature, "passed": verdict == "pass", "observation": "Synthetic fixture checked"} for feature in request["required_features"]],
        "issues": [] if verdict == "pass" else ["A required reference feature is missing"],
    }


def approve_visual(engine, run_id):
    return engine.accept_visual_review(run_id, visual_review(engine, run_id))


def make_reference(path: Path, *, variant: str = "good") -> None:
    image = Image.new("RGB", (128, 128), (210, 225, 240))
    draw = ImageDraw.Draw(image)
    if variant == "good":
        draw.rectangle((25, 40, 105, 110), fill=(180, 175, 165), outline=(30, 30, 30), width=3)
        draw.rectangle((48, 60, 80, 88), fill=(45, 75, 95), outline=(20, 20, 20), width=2)
    else:
        draw.ellipse((15, 15, 110, 110), fill=(220, 30, 30))
    image.save(path)


class FakeWorker:
    def __init__(self, reference: Path, *, first_variant: str = "good"):
        self.reference = reference
        self.first_variant = first_variant
        self.calls = 0

    def run(self, job_path: Path, log_path: Path) -> JobResult:
        job = JobRequest.load(job_path)
        outputs = {name: Path(value) for name, value in job.outputs.items()}
        for name in ("blend", "glb"):
            outputs[name].parent.mkdir(parents=True, exist_ok=True)
            outputs[name].write_bytes(f"{name}-{self.calls}".encode())
        render_variant = self.first_variant if self.calls == 0 else "good"
        if render_variant == "good":
            outputs["preview"].parent.mkdir(parents=True, exist_ok=True)
            with Image.open(self.reference) as image:
                image.convert("RGBA").save(outputs["preview"])
        else:
            make_reference(outputs["preview"], variant="bad")
        atomic_write_json(
            outputs["scene_manifest"],
            {"schema_version": 1, "units": "meters", "objects": [{"name": "Wall.Front", "type": "MESH"}]},
        )
        artifacts = [
            {"name": name, "path": str(outputs[name]), "sha256": sha256_file(outputs[name])}
            for name in ("blend", "glb", "preview", "scene_manifest")
        ]
        result = JobResult(
            job_id=job.job_id,
            status="succeeded",
            artifacts=artifacts,
            metrics={"mesh_object_count": 1, "camera_locked": True},
        )
        result.save(outputs["result"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("fake worker", encoding="utf-8")
        self.calls += 1
        return result
