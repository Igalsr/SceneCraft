"""Strict, evidence-bound visual review supplied by the active agent or a human."""
from .contracts import _exact_keys, _object, _text
from .errors import ContractError


def validate_visual_review(value, request, request_sha256):
    _object(value, "visual review")
    _exact_keys(value, "visual review", {"schema_version", "run_id", "iteration", "request_sha256", "reviewer", "verdict", "features", "issues"})
    if value["schema_version"] != 1 or value["run_id"] != request["run_id"] or value["iteration"] != request["iteration"]:
        raise ContractError("Visual review identity does not match the request")
    if value["request_sha256"] != request_sha256:
        raise ContractError("Visual review is based on stale evidence")
    if value["reviewer"] not in {"astra-agent", "human"} or value["verdict"] not in {"pass", "repair"}:
        raise ContractError("Unsupported reviewer or verdict")
    if not isinstance(value["features"], list) or not value["features"]:
        raise ContractError("Visual review must check all required features")
    seen = set()
    for feature in value["features"]:
        _object(feature, "feature review")
        _exact_keys(feature, "feature review", {"id", "passed", "observation"})
        _text(feature["id"], "feature id", max_length=200)
        _text(feature["observation"], "feature observation")
        if feature["id"] in seen or type(feature["passed"]) is not bool:
            raise ContractError("Duplicate feature or invalid pass flag")
        seen.add(feature["id"])
    if not set(request["required_features"]) <= seen:
        raise ContractError("Visual review omits required features")
    if not isinstance(value["issues"], list) or len(value["issues"]) > 200:
        raise ContractError("issues must be an array of at most 200 items")
    for issue in value["issues"]:
        _text(issue, "review issue")
    if value["verdict"] == "pass" and (value["issues"] or not all(feature["passed"] for feature in value["features"])):
        raise ContractError("A passing review cannot contain failed features or outstanding issues")
    if value["verdict"] == "repair" and not value["issues"]:
        raise ContractError("A repair verdict must explain the issue")
    return value
