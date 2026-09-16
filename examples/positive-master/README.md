# Positive-master fixture

`scene-spec.json` defines a synthetic rounded pawn with a 50 mm circular base and 81 mm total height. It is a positive master, not a negative silicone mold. Named primitive operands are combined with exact boolean union. The neck is an undercut that needs an explicit split/cut mold release strategy.

Run `python scripts/benchmark_master.py /absolute/path/to/new-benchmark --blender /path/to/blender` from an installed checkout. It creates a reference from this known fixture, tests rejection of a missing head, rebuilds the corrected plan, and stops for a real visual review. The source and generated fixture evidence are covered by the repository's 0BSD license. This benchmark establishes pipeline behavior; it does not establish reconstruction quality on arbitrary images or fabrication suitability.
