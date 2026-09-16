# Workflow and gates

The canonical order is ingest, analyze, plan, build, render, evaluate, repair, rebuild, package, and learn. Runs may loop from repair back through the trusted build but may not skip acceptance or the final learning phase.

The current Astra task performs analyze, visual critique, repair planning, and learning synthesis. The Python runtime performs schema validation, checkpointing, metrics, trusted Blender operations, and memory storage. Do not install or invoke the OpenAI SDK from the runtime.

Evaluation requires both deterministic checks and a recorded visual review. The runtime measures silhouette overlap, edge alignment, and pixel similarity and checks geometry, render completion, and exports. It then waits for `resume --review` with a request-hash-bound review covering all features. Rejected visual reviews enter the repair loop even when all image metrics pass.

Prioritize repairs in this order: camera and framing, global envelope and silhouette, large voids and roofline, facade openings and rhythm, materials, then small detail. Make bounded changes attributable to observed failures. Preserve the prior evidence and score after every iteration.

Stop successfully only when every required view and hard check passes. Stop unsuccessfully when the iteration budget is exhausted, the score regresses repeatedly, Blender fails reproducibly, or missing evidence makes the target underdetermined. In that case, retain the best-scoring artifact and state the precise limitation.

The package includes `.blend`, `.glb`, scene manifest/specification, reference manifest, hero evidence, visual review, accepted evaluation, repair history, provenance, and uncertainty report. Objects/masters additionally include `master-mm.stl` and a geometry report. The run-level learning report and full lesson artifacts remain alongside the package and are required for completion. Failed-run closeout never marks the model successful.
