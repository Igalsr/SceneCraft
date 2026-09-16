"""Repository-owned object/master construction; all operands are declarative data."""
from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path


def sha256(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def mesh_audit(obj, spec):
    import bmesh
    from mathutils.bvhtree import BVHTree

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    bm.normal_update()
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    unseen = set(bm.verts)
    components = 0
    while unseen:
        components += 1
        stack = [unseen.pop()]
        while stack:
            vertex = stack.pop()
            for edge in vertex.link_edges:
                neighbor = edge.other_vert(vertex)
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
    non_manifold = sum(not edge.is_manifold for edge in bm.edges)
    inconsistent = sum(edge.is_manifold and not edge.is_contiguous for edge in bm.edges)
    loose_vertices = sum(not vertex.link_faces for vertex in bm.verts)
    degenerate = sum(face.calc_area() < 1e-16 for face in bm.faces)
    volume = bm.calc_volume(signed=True)
    tree = BVHTree.FromBMesh(bm, epsilon=0.0)
    intersecting = set()
    for left, right in tree.overlap(tree):
        if left >= right:
            continue
        if not set(bm.faces[left].verts) & set(bm.faces[right].verts):
            intersecting.add((left, right))
    dimensions = [max(v.co[i] for v in bm.verts) - min(v.co[i] for v in bm.verts) for i in range(3)] if bm.verts else [0, 0, 0]
    manufacturing = spec.get("manufacturing")
    dimension_pass = True
    if manufacturing:
        dimension_pass = all(abs(actual - expected) <= manufacturing["dimension_tolerance_m"] for actual, expected in zip(dimensions, manufacturing["target_dimensions_m"]))
    report = {
        "schema_version": 1, "kind": spec["kind"], "units": "meters", "stl_units": "millimeters",
        "dimensions_m": dimensions, "volume_m3": volume, "components": components,
        "non_manifold_edges": non_manifold, "inconsistent_edges": inconsistent,
        "loose_vertices": loose_vertices, "degenerate_faces": degenerate,
        "detected_intersections": len(intersecting), "dimensions_passed": dimension_pass,
        "passed": bool(bm.faces) and components == 1 and non_manifold == 0 and inconsistent == 0 and loose_vertices == 0 and degenerate == 0 and volume > 0 and not intersecting and dimension_pass,
        "manual_checks_required": ["minimum feature thickness", "undercuts and silicone release strategy", "surface finish and printer suitability"],
        "limitations": "Intersection screening excludes adjacent faces; this is not a complete manufacturing certification. Thin features and demolding require visual/process review.",
    }
    bm.free()
    return report


def export_stl_mm(obj, path):
    """Write only the finished object's triangles; STL coordinates explicitly use mm."""
    obj.data.calc_loop_triangles()
    triangles = obj.data.loop_triangles
    with path.open("wb") as handle:
        handle.write(b"SceneCraft positive/object master; coordinates in millimeters".ljust(80, b"\0"))
        handle.write(struct.pack("<I", len(triangles)))
        for triangle in triangles:
            coordinates = [obj.matrix_world @ obj.data.vertices[index].co for index in triangle.vertices]
            normal = (coordinates[1] - coordinates[0]).cross(coordinates[2] - coordinates[0]).normalized()
            values = list(normal) + [float(component) * 1000 for vertex in coordinates for component in vertex]
            handle.write(struct.pack("<12fH", *values, 0))


def operand(bpy, collection, item):
    primitive = item["primitive"]
    if primitive == "box":
        bpy.ops.mesh.primitive_cube_add(size=1)
    elif primitive == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=0.5)
    elif primitive == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.5, depth=1)
    elif primitive == "cone":
        bpy.ops.mesh.primitive_cone_add(vertices=64, radius1=0.5, radius2=0, depth=1)
    elif primitive == "torus":
        bpy.ops.mesh.primitive_torus_add(major_segments=64, minor_segments=24, major_radius=0.35, minor_radius=0.15)
    elif primitive == "mesh":
        mesh = bpy.data.meshes.new(f"Operand.{item['id']}.Mesh")
        mesh.from_pydata(item["vertices"], [], item["faces"])
        mesh.update()
        obj = bpy.data.objects.new(f"Operand.{item['id']}", mesh)
        collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
    else:
        raise ValueError(f"Unsupported primitive: {primitive}")
    obj = bpy.context.object
    obj.name = f"Operand.{item['id']}"
    bpy.context.view_layer.update()
    if primitive == "mesh" and min(obj.dimensions) <= 0:
        raise ValueError("Explicit mesh must span three dimensions")
    obj.dimensions = item["dimensions"]
    obj.location = item["center"]
    obj.rotation_euler = [math.radians(value) for value in item["rotation_deg"]]
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    for current in list(obj.users_collection):
        current.objects.unlink(obj)
    collection.objects.link(obj)
    material = bpy.data.materials.new(f"MAT.{item['id']}")
    material.diffuse_color = (*item["color"], 1)
    material.use_nodes = True
    material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*item["color"], 1)
    material.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.55
    obj.data.materials.append(material)
    return obj


def build_object(job):
    import bmesh
    import bpy
    from mathutils import Vector

    root = Path(job["workspace_root"]).resolve()
    paths = {name: Path(value).resolve() for name, value in job["outputs"].items()}
    spec_path = Path(job["inputs"]["building_spec"]).resolve()
    for path in [spec_path, *paths.values()]:
        if root not in path.parents:
            raise ValueError("Object job path escapes its project")
    spec = json.loads(spec_path.read_text())
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)
    source_collection = bpy.data.collections.new("MODEL.Operands")
    bpy.context.scene.collection.children.link(source_collection)
    model_collection = bpy.data.collections.new("MODEL.Master")
    bpy.context.scene.collection.children.link(model_collection)
    objects = []
    for item in spec["objects"]:
        bpy.ops.object.select_all(action="DESELECT")
        objects.append(operand(bpy, source_collection, item))
    final = objects[0].copy()
    final.data = objects[0].data.copy()
    final.name = "Master.Positive" if spec["kind"] == "positive-master" else "Model.Object"
    final["scenecraft_semantic"] = spec["kind"]
    model_collection.objects.link(final)
    bpy.context.view_layer.objects.active = final
    final.select_set(True)
    for item, obj in zip(spec["objects"][1:], objects[1:]):
        modifier = final.modifiers.new(f"CSG.{item['id']}", "BOOLEAN")
        modifier.object = obj
        modifier.operation = item["operation"].upper()
        modifier.solver = "EXACT"
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    # Keep semantic operands editable in the native file but never render/export them.
    for obj in objects:
        obj.select_set(False)
    source_collection.hide_render = True
    source_collection.hide_viewport = True
    bm = bmesh.new()
    bm.from_mesh(final.data)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(final.data)
    bm.free()
    final.data.update()
    bpy.context.view_layer.update()
    report = mesh_audit(final, spec)
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    paths["geometry_report"].write_text(json.dumps(report, indent=2) + "\n")
    export_stl_mm(final, paths["stl"])

    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1
    camera_data = bpy.data.cameras.new("Camera.Hero")
    camera = bpy.data.objects.new("Camera.Hero", camera_data)
    scene.collection.objects.link(camera)
    camera.location = spec["camera"]["position"]
    camera.rotation_euler = (Vector(spec["camera"]["target"]) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.lens = spec["camera"]["lens_mm"]
    camera.data.clip_start = 0.0001
    camera.data.clip_end = 1000
    scene.camera = camera
    light_data = bpy.data.lights.new("Light.Sun", "SUN")
    light_data.energy = 2.5
    light = bpy.data.objects.new("Light.Sun", light_data)
    scene.collection.objects.link(light)
    light.rotation_euler = (0.5, -0.3, -0.6)
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.5, 0.5, 0.5, 1)
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.8
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.render.resolution_x = job["settings"].get("render_width", 640)
    scene.render.resolution_y = job["settings"].get("render_height", 640)
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(paths["preview"])
    bpy.ops.object.select_all(action="DESELECT")
    final.select_set(True)
    bpy.context.view_layer.objects.active = final
    bpy.ops.wm.save_as_mainfile(filepath=str(paths["blend"]))
    bpy.ops.export_scene.gltf(filepath=str(paths["glb"]), export_format="GLB", use_selection=True)
    bpy.ops.render.render(write_still=True)
    # Extra views inspect the solid; they do not claim fidelity to unseen references.
    center = sum((final.matrix_world @ Vector(corner) for corner in final.bound_box), Vector()) / 8
    distance = max(final.dimensions) * 3
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(final.dimensions) * 1.35
    scene.render.resolution_x = 256
    scene.render.resolution_y = 256
    for view, direction in {"back": (0, 1, 0), "side": (1, 0, 0), "top": (0, 0, 1)}.items():
        camera.location = center + Vector(direction) * distance
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(paths[f"inspection_{view}"])
        bpy.ops.render.render(write_still=True)
    manifest = {
        "schema_version": 1, "units": "meters", "stl_units": "millimeters",
        "source_spec_sha256": sha256(spec_path), "blender_version": bpy.app.version_string,
        "objects": [{"name": obj.name, "type": obj.type, "semantic": item["id"], "operation": item["operation"]} for obj, item in zip(objects, spec["objects"])],
        "exported_object": final.name,
    }
    paths["scene_manifest"].write_text(json.dumps(manifest, indent=2) + "\n")
    artifacts = [{"name": name, "path": str(path), "sha256": sha256(path)} for name, path in paths.items() if name != "result"]
    return artifacts, {"mesh_object_count": 1, "camera_locked": True, "geometry_passed": report["passed"], "blender_version": bpy.app.version_string}, []
