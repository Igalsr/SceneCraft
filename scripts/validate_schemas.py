from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    schemas = sorted((root / "schemas").glob("*.schema.json"))
    if not schemas:
        raise SystemExit("no schemas found")
    for path in schemas:
        value = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(value)
        print(path.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
