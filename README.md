# SceneCraft

SceneCraft turns reference images into 3D objects, figures, positive masters for silicone molds, or buildings using Astra and headless Blender. Astra runs in the user's Codex account and produces JSON plans, visual reviews, repairs, and lessons. Repository code validates the artifacts and operates Blender. No OpenAI SDK, API key, or nested model call is required.

The first release implements the `hero-view` workflow end to end:

`reference → Astra plan → Blender build/render → metrics + visual review → repair loop → accepted package → learning`

Retries archive the previous attempt's outputs and logs. Evaluation failures resume from verified renders. A successful run requires passing metrics, an evidence-bound visual review, a verified package, and a closed retrospective. Failed runs can also record lessons without being marked successful.

## Requirements

- Python 3.11–3.14
- Blender 4.5 LTS; the container pins Blender 4.5.13
- A Codex account with GPT-6 Astra when using agent planning and visual critique

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
scenecraft doctor
```

The Python package depends on Pillow for reference decoding and deterministic image metrics. It does not install an OpenAI package.

## Run a reconstruction

```bash
scenecraft init ./my-object --name "My Figure" --asset-type positive-master
scenecraft add-reference ./my-object ./hero-view.png --role primary --view hero
scenecraft run ./my-object
```

Choose `positive-master` for the positive object you pour silicone around, `object` for general modeling, or `building` for architectural scenes. A positive master requires user-specified dimensions, tolerance, minimum feature size, scale source, and release strategy. Image similarity alone cannot establish physical scale.

The run waits at `analyze_references` and writes `analysis-request.json`. In the active Astra task, inspect the reference and frozen request, then write a specification matching `schemas/scene-spec.schema.json`. Object/master plans use `object-spec.schema.json`; buildings use `building-spec.schema.json`. Submit it:

```bash
scenecraft resume ./my-object <run-id> \
  --spec ./my-object/runs/<run-id>/plan/agent-scene-spec.json \
  --plan-source astra-agent \
  --blender /path/to/blender
```

If the metrics fail, the same run waits at `repair_model` with a repair request. Astra returns a complete revised specification conforming to `schemas/repair.schema.json`:

```bash
scenecraft resume ./my-object <run-id> \
  --repair ./my-object/runs/<run-id>/repairs/agent-repair.json \
  --plan-source astra-agent \
  --blender /path/to/blender
```

Repair v2 retains the legacy field name `building_spec`, which now accepts either plan type.

When metrics pass, the run waits for visual review. Inspect the reference, render, comparison, and `iterations/<iteration>/visual-review-request.json`. Submit a review conforming to `schemas/visual-review.schema.json`, with the request SHA-256 and observations for every required feature:

```bash
scenecraft resume ./my-object <run-id> --review ./review.json
```

A rejected visual review starts another repair even when all image metrics pass. Accepted deliverables include `.blend`, `.glb`, hero evidence, scene manifest, visual review, evaluation, provenance, repairs, and uncertainty. Objects and masters also include `master-mm.stl` (millimeter coordinates) and `geometry-report.json`; `.blend` and GLB remain in meters. Completion re-hashes every packaged file.

Positive masters must have one closed, consistently oriented component, positive volume, no detected nonadjacent intersections, and dimensions within tolerance. The review must address thin features, undercuts, release strategy and surface/printing suitability. These checks are not a fabrication certification. See [positive-master guidance](plugins/scenecraft/skills/scenecraft/references/positive-masters.md).

## Capture learning

Lessons are validated from stored evaluations, not caller-supplied scores:

```bash
scenecraft learn ./my-object <run-id> \
  --before-iteration 0 --after-iteration 1 \
  --action-key camera.hero-focal-length \
  --stage evaluate_fidelity \
  --trigger "Perspective convergence was too strong" \
  --learning "The repaired lens and distance improved every stored metric" \
  --action "Calibrate the hero camera before changing facade detail" \
  --confidence 0.9

scenecraft complete ./my-object <run-id>
```

When there was no reusable improvement, close the phase explicitly:

```bash
scenecraft complete ./my-object <run-id> \
  --no-lessons-reason "The initial plan passed without a repair."
```

Validated project lessons are frozen into the next analysis request. To share generalized workflow lessons between projects, set `SCENECRAFT_WORKFLOW_MEMORY` to a reviewed `knowledge/lessons.json` file.

Alternatively, persist the shared store with `scenecraft configure-memory ./my-object /absolute/path/to/shared-lessons.json` on each participating project. Use `learn --memory-scope workflow` only for generalized lessons. Failed runs support the same measured learning command; unmeasured lessons use `scenecraft note ./my-object <run-id> --action-key <key> --learning <observation> --action <next-action>`. Notes remain inactive candidates. `complete` closes a failed run's retrospective while keeping its failed status.

## Fidelity boundary

SceneCraft measures similarity against declared views; it does not claim that one image reveals hidden geometry or absolute scale. Metrics are silhouette IoU, tolerant edge F1, and mean pixel similarity; mandatory visual review checks details the metrics miss. Objects support primitive solids, union/difference, and explicit mesh data, not arbitrary executable modeling scripts. Complex organic figures may require detailed mesh plans and more references. `multi-view` and `metric` workflows remain blocked until their full acceptance gates are implemented.

The benchmark in `scripts/benchmark_master.py` deliberately removes a pawn's head, repairs it, and stops for real visual review. Its reference comes from a known synthetic fixture. It tests execution and recovery, not arbitrary-image reconstruction. Earlier pre-release runs lacking frozen input hashes must be preserved and started as new runs; analysis and evaluation schemas are now v3.

## Share it

The Git repository is the canonical distribution for the runtime, public schemas, trusted Blender runner, tests, pinned container, and Codex plugin. See [docs/sharing.md](docs/sharing.md) for collaborator setup and [docs/architecture.md](docs/architecture.md) for the trust and evidence model.

SceneCraft is released under the [BSD Zero Clause License](LICENSE), allowing use, modification, and redistribution for any purpose without an attribution requirement.
