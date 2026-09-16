import math
from importlib import resources
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .contracts import _number, _vector
from .errors import ContractError
from .util import read_json


def validate_object_spec(value):
    source = Path(__file__).resolve().parents[2] / "schemas"
    root = source if source.is_dir() else Path(str(resources.files("scenecraft").joinpath("resources/schemas")))
    schemas = [read_json(root / name) for name in ("object-spec.schema.json", "building-spec.schema.json")]
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
    errors = list(Draft202012Validator(schemas[0], registry=registry).iter_errors(value))
    if errors:
        raise ContractError(f"Invalid object specification: {errors[0].message}")

    def finite(item):
        if isinstance(item, float) and not math.isfinite(item):
            raise ContractError("Object specification contains a non-finite number")
        if isinstance(item, (list, dict)):
            for child in item.values() if isinstance(item, dict) else item:
                finite(child)
    finite(value)
    if value["camera"]["position"] == value["camera"]["target"]:
        raise ContractError("Camera position and target must differ")
    _vector(value["camera"]["position"], "camera.position", 3)
    _number(value["camera"]["lens_mm"], "camera.lens_mm")
    if value["objects"][0]["operation"] != "union":
        raise ContractError("First object must be a union operand")
    identifiers = [item["id"] for item in value["objects"]]
    if len(set(identifiers)) != len(identifiers):
        raise ContractError("Object ids must be unique")
    for item in value["objects"]:
        if item["primitive"] == "mesh" and any(index >= len(item["vertices"]) for face in item["faces"] for index in face):
            raise ContractError("Mesh face index exceeds the vertex array")
    return value
