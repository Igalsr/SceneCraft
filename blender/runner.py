"""Trusted SceneCraft Blender worker.

Invoke only through Blender. Jobs contain data, never executable code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import traceback
from pathlib import Path


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")  # noqa: TRY004
    return value


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def inside(root: Path, value) -> Path:
    root = root.resolve()
    path = Path(value).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"Job path escapes workspace root: {path}")
    return path


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def parse_args() -> argparse.Namespace:
    script_args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    return parser.parse_args(script_args)


def material(bpy, name: str, rgb: list[float], roughness: float = 0.5, alpha: float = 1.0):
    value = bpy.data.materials.new(name)
    value.diffuse_color = (*rgb, alpha)
    value.use_nodes = True
    node = value.node_tree.nodes.get("Principled BSDF")
    node.inputs["Base Color"].default_value = (*rgb, alpha)
    node.inputs["Roughness"].default_value = roughness
    node.inputs["Alpha"].default_value = alpha
    if alpha < 1:
        value.surface_render_method = "DITHERED"
    return value


def add_box(bpy, collection, name: str, location, dimensions, surface, rotation_deg: float = 0):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    obj.rotation_euler[2] = math.radians(rotation_deg)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    for current in list(obj.users_collection):
        current.objects.unlink(obj)
    collection.objects.link(obj)
    obj.data.materials.append(surface)
    obj["scenecraft_semantic"] = name.split(".", 1)[0]
    return obj


def add_gable_roof(bpy, collection, width, depth, height, pitch_deg, overhang, surface):
    half_width = width / 2 + overhang
    half_depth = depth / 2 + overhang
    rise = math.tan(math.radians(pitch_deg)) * half_width
    vertices = [
        (-half_width, -half_depth, height), (half_width, -half_depth, height),
        (-half_width, half_depth, height), (half_width, half_depth, height),
        (0, -half_depth, height + rise), (0, half_depth, height + rise),
    ]
    faces = [(0, 1, 4), (2, 5, 3), (0, 4, 5, 2), (1, 3, 5, 4), (0, 2, 3, 1)]
    mesh = bpy.data.meshes.new("Roof.Gable.Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("Roof.Gable", mesh)
    collection.objects.link(obj)
    obj.data.materials.append(surface)
    obj["scenecraft_semantic"] = "Roof"


def add_opening(bpy, collection, opening, width, depth, thickness, glass, frame):
    horizontal, vertical = [float(value) for value in opening["center"]]
    opening_width = float(opening["width"])
    opening_height = float(opening["height"])
    frame_width = float(opening.get("frame_width", 0.08))
    facade = opening["facade"]
    offset = 0.005
    if facade == "front":
        location, dimensions = (horizontal, -depth / 2 - offset, vertical), (opening_width, 0.04, opening_height)
        horizontal_axis = "x"
    elif facade == "back":
        location, dimensions = (-horizontal, depth / 2 + offset, vertical), (opening_width, 0.04, opening_height)
        horizontal_axis = "x"
    elif facade == "left":
        location, dimensions = (-width / 2 - offset, horizontal, vertical), (0.04, opening_width, opening_height)
        horizontal_axis = "y"
    else:
        location, dimensions = (width / 2 + offset, -horizontal, vertical), (0.04, opening_width, opening_height)
        horizontal_axis = "y"
    semantic = "Door" if opening["kind"] == "door" else "Window"
    add_box(bpy, collection, f"{semantic}.{opening['id']}.Glass", location, dimensions, glass)
    frame_depth = 0.06
    if horizontal_axis == "x":
        axis_center = location[0]
        bars = [
            ((location[0], location[1], vertical - opening_height / 2), (opening_width + frame_width * 2, frame_depth, frame_width)),
            ((location[0], location[1], vertical + opening_height / 2), (opening_width + frame_width * 2, frame_depth, frame_width)),
            ((axis_center - opening_width / 2, location[1], vertical), (frame_width, frame_depth, opening_height)),
            ((axis_center + opening_width / 2, location[1], vertical), (frame_width, frame_depth, opening_height)),
        ]
    else:
        axis_center = location[1]
        bars = [
            ((location[0], location[1], vertical - opening_height / 2), (frame_depth, opening_width + frame_width * 2, frame_width)),
            ((location[0], location[1], vertical + opening_height / 2), (frame_depth, opening_width + frame_width * 2, frame_width)),
            ((location[0], axis_center - opening_width / 2, vertical), (frame_depth, frame_width, opening_height)),
            ((location[0], axis_center + opening_width / 2, vertical), (frame_depth, frame_width, opening_height)),
        ]
    for index, (bar_location, bar_dimensions) in enumerate(bars):
        add_box(bpy, collection, f"{semantic}.{opening['id']}.Frame.{index}", bar_location, bar_dimensions, frame)


def aim_camera(camera, target, Vector):
    direction = Vector(target) - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def clean_scene(bpy):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)


def create_collection(bpy, parent, name):
    collection = bpy.data.collections.new(name)
    parent.children.link(collection)
    return collection


def build_scene(job: dict) -> tuple[list[dict], dict, list[str]]:
    import bpy
    from mathutils import Vector

    root = Path(job["workspace_root"]).resolve()
    spec_path = inside(root, job["inputs"]["building_spec"])
    outputs = {name: inside(root, value) for name, value in job["outputs"].items()}
    spec = read_json(spec_path)
    width = float(spec["envelope"]["width"])
    depth = float(spec["envelope"]["depth"])
    height = float(spec["envelope"]["height"])
    floors = int(spec["floors"])
    thickness = float(spec["wall_thickness"])
    if min(width, depth, height, thickness) <= 0 or floors < 1:
        raise ValueError("Building dimensions and floor count must be positive")

    clean_scene(bpy)
    root_collection = bpy.context.scene.collection
    scene_collection = create_collection(bpy, root_collection, "SCENECRAFT")
    envelope_collection = create_collection(bpy, scene_collection, "ARCH.Envelope")
    volume_collection = create_collection(bpy, scene_collection, "ARCH.Volumes")
    opening_collection = create_collection(bpy, scene_collection, "ARCH.Openings")
    element_collection = create_collection(bpy, scene_collection, "ARCH.Elements")
    camera_collection = create_collection(bpy, scene_collection, "EVIDENCE.Cameras")
    light_collection = create_collection(bpy, scene_collection, "EVIDENCE.Lights")

    colors = spec["materials"]
    surfaces = {
        "wall": material(bpy, "MAT.Wall", colors["wall_rgb"], 0.62),
        "roof": material(bpy, "MAT.Roof", colors["roof_rgb"], 0.48),
        "glass": material(bpy, "MAT.Glass", colors["glass_rgb"], 0.22, 0.72),
        "accent": material(bpy, "MAT.Accent", colors.get("accent_rgb", colors["roof_rgb"]), 0.42),
    }

    half_h = height / 2.0
    walls = [
        ("Wall.Front", (0, -depth / 2 + thickness / 2, half_h), (width, thickness, height)),
        ("Wall.Back", (0, depth / 2 - thickness / 2, half_h), (width, thickness, height)),
        ("Wall.Left", (-width / 2 + thickness / 2, 0, half_h), (thickness, depth - 2 * thickness, height)),
        ("Wall.Right", (width / 2 - thickness / 2, 0, half_h), (thickness, depth - 2 * thickness, height)),
    ]
    wall_objects = {}
    for name, location, dimensions in walls:
        wall_objects[name] = add_box(bpy, envelope_collection, name, location, dimensions, surfaces["wall"])
    roof = spec.get("roof", {"type": "flat"})
    floor_height = height / floors
    for index in range(floors + 1):
        z = min(index * floor_height, height)
        overhang = float(roof.get("overhang", 0)) if index == floors and roof["type"] == "flat" else 0
        add_box(bpy, envelope_collection, f"Slab.{index:02d}", (0, 0, z), (width + 2 * overhang, depth + 2 * overhang, 0.18), surfaces["roof"] if index == floors else surfaces["wall"])

    for volume in spec.get("volumes", []):
        add_box(bpy, volume_collection, f"Volume.{volume['id']}", volume["center"], volume["dimensions"], surfaces[volume["material"]], float(volume.get("rotation_deg", 0)))
    for opening in spec.get("openings", []):
        horizontal, vertical = opening["center"]
        facade = opening["facade"]
        if facade in {"front", "back"}:
            location = (horizontal if facade == "front" else -horizontal, -depth / 2 if facade == "front" else depth / 2, vertical)
            dimensions = (opening["width"], thickness * 3, opening["height"])
        else:
            location = (-width / 2 if facade == "left" else width / 2, horizontal if facade == "left" else -horizontal, vertical)
            dimensions = (thickness * 3, opening["width"], opening["height"])
        cutter = add_box(bpy, opening_collection, f"Cutter.{opening['id']}", location, dimensions, surfaces["wall"])
        wall = wall_objects[f"Wall.{facade.title()}"]
        bpy.context.view_layer.objects.active = wall
        modifier = wall.modifiers.new(f"Opening.{opening['id']}", "BOOLEAN")
        modifier.operation = "DIFFERENCE"
        modifier.solver = "EXACT"
        modifier.object = cutter
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        bpy.data.objects.remove(cutter, do_unlink=True)
        add_opening(bpy, opening_collection, opening, width, depth, thickness, surfaces["glass"], surfaces["accent"])
    for element in spec.get("elements", []):
        add_box(bpy, element_collection, f"{element['semantic'].title()}.{element['id']}", element["center"], element["dimensions"], surfaces[element["material"]], float(element.get("rotation_deg", 0)))

    if roof["type"] == "gable":
        add_gable_roof(bpy, envelope_collection, width, depth, height, float(roof.get("pitch_degrees", 30)), float(roof.get("overhang", 0)), surfaces["roof"])

    camera_data = bpy.data.cameras.new("Camera.Hero")
    camera = bpy.data.objects.new("Camera.Hero", camera_data)
    camera_collection.objects.link(camera)
    camera.location = spec["camera"]["position"]
    camera.data.lens = float(spec["camera"]["lens_mm"])
    aim_camera(camera, spec["camera"]["target"], Vector)
    bpy.context.scene.camera = camera

    sun_data = bpy.data.lights.new("Light.Sun", type="SUN")
    sun = bpy.data.objects.new("Light.Sun", sun_data)
    light_collection.objects.link(sun)
    sun.rotation_euler = (math.radians(32), math.radians(-18), math.radians(-35))
    sun.data.energy = 2.5
    area_data = bpy.data.lights.new("Light.Fill", type="AREA")
    area = bpy.data.objects.new("Light.Fill", area_data)
    light_collection.objects.link(area)
    area.location = (-width, -depth, height * 1.5)
    area.data.energy = 700
    area.data.shape = "DISK"
    area.data.size = max(width, depth)

    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.render.resolution_x = int(job.get("settings", {}).get("render_width", 640))
    scene.render.resolution_y = int(job.get("settings", {}).get("render_height", 640))
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = True
    scene.render.filepath = str(outputs["preview"])
    scene.world.color = (0.055, 0.065, 0.08)

    for path in outputs.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(outputs["blend"]))
    bpy.ops.export_scene.gltf(filepath=str(outputs["glb"]), export_format="GLB")
    bpy.ops.render.render(write_still=True)

    objects = []
    for obj in sorted(bpy.data.objects, key=lambda item: item.name):
        objects.append({
            "name": obj.name,
            "type": obj.type,
            "location": [round(float(v), 6) for v in obj.location],
            "dimensions": [round(float(v), 6) for v in obj.dimensions],
            "semantic": obj.get("scenecraft_semantic"),
        })
    atomic_json(outputs["scene_manifest"], {
        "schema_version": 1, "units": "meters", "source_spec_sha256": digest(spec_path),
        "blender_version": bpy.app.version_string, "objects": objects,
    })
    artifacts = [
        {"name": name, "path": str(outputs[name]), "sha256": digest(outputs[name])}
        for name in ("blend", "glb", "preview", "scene_manifest")
    ]
    mesh_count = sum(item["type"] == "MESH" for item in objects)
    warnings = []
    if not spec.get("openings"):
        warnings.append("No facade openings were declared in the building specification.")
    return artifacts, {
        "object_count": len(objects), "mesh_object_count": mesh_count,
        "floor_count": floors, "camera_locked": True, "blender_version": bpy.app.version_string,
    }, warnings


def failure_result(job_id: str, error: str) -> dict:
    return {
        "schema_version": 2, "job_id": job_id, "status": "failed", "artifacts": [],
        "metrics": {}, "warnings": [], "error": error,
    }


def main() -> int:
    args = parse_args()
    job = None
    result_path = args.job.resolve().parent / "result.json"
    try:
        job = read_json(args.job.resolve())
        if job.get("schema_version") != 2 or job.get("operation") not in {"build_scene", "build_object"}:
            raise ValueError("Unsupported SceneCraft job")
        root = Path(job["workspace_root"]).resolve()
        inside(root, args.job)
        result_path = inside(root, job["outputs"]["result"])
        if job["operation"] == "build_object":
            # This sibling module ships with the trusted runner, never with user plans.
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from object_runner import build_object
            artifacts, metrics, warnings = build_object(job)
        else:
            artifacts, metrics, warnings = build_scene(job)
        atomic_json(result_path, {
            "schema_version": 2, "job_id": job["job_id"], "status": "succeeded",
            "artifacts": artifacts, "metrics": metrics, "warnings": warnings, "error": None,
        })
        return 0
    except Exception as exc:  # noqa: BLE001 - every Blender failure must emit a result artifact
        try:
            atomic_json(result_path, failure_result(
                job.get("job_id", "unknown") if isinstance(job, dict) else "unknown",
                f"{exc}\n{traceback.format_exc()}",
            ))
        except Exception:  # noqa: BLE001 - best-effort fallback cannot hide the original failure
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
