# Project contract

A project contains `.scenecraft/project.json`, `.scenecraft/reference-manifest.json`, immutable `inputs/references/`, checkpointed `runs/`, shared `artifacts/`, and accepted `deliverables/`.

Project learning memory lives at `.scenecraft/learning/lessons.json`. A run freezes applied lessons at `runs/<run-id>/inputs/applied-lessons.json` and writes its retrospective to `runs/<run-id>/learning/report.json`. Shared cross-project lessons come from the path selected by `SCENECRAFT_WORKFLOW_MEMORY`.

The active Astra task writes a proposed scene specification and submits it to the CLI. The runtime copies it to `runs/<run-id>/plan/iterations/<iteration>-building-spec.json` (a retained legacy filename) and records `plan/provenance.json`. Repair v2 retains the `building_spec` field for either schema. Provenance distinguishes `astra-agent` plans, which may apply frozen lessons, from `manual` plans.

Validate artifacts against `schemas/`. Building/object specifications and visual reviews use v1; job, result, repair, reference-manifest, learning-memory and learning-report use v2; evaluation and analysis-request use v3. Memory v1 is readable and upgrades on the next save; unmeasured v2 observations have null scores. Resume only new-format runs with frozen input hashes; older pre-release checkpoints must be preserved and started as a new run after reimporting their references.

Each reference entry records a SHA-256, role, view label, and project-relative file. Digests are verified at start, build, evaluation, review, packaging and completion. Frozen project and manifest files are also hash-checked.

Blender jobs use allowlisted `build_scene` or `build_object` operations and explicit inputs/outputs. All paths must resolve under `workspace_root`. A worker result must match job ID, declared paths, and hashes. Retries archive all previous outputs and logs in the job's `attempts/` directory. Evaluation resumes from verified artifacts without rebuilding.
