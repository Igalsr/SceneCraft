---
name: scenecraft
description: Create and refine reference-based 3D objects, figures, positive masters for silicone molds, or buildings using Astra planning and trusted headless Blender. Use for SceneCraft projects, render comparisons, structured repairs, mesh checks, exports, and reusable run lessons.
---

# Scenecraft

Operate the repository workflow; do not replace it with a long one-off prompt.

## Start or inspect

1. Locate the repository root and run `python -m scenecraft doctor` or `scenecraft doctor`.
2. If no project exists, initialize one with `--asset-type object`, `positive-master`, or `building`. Import exactly one primary hero reference; other images are supporting evidence.
3. Preserve imported references. Add a new reference instead of editing evidence already in the manifest.
4. Read [references/project-contract.md](references/project-contract.md) before changing project or artifact JSON.
5. For a positive master that the user will pour silicone around, read [references/positive-masters.md](references/positive-masters.md). Obtain the user's target dimensions and intended release strategy before constructing a manufacturing plan.

## Run

1. Use `hero-view` for executable runs in this release. Read [references/fidelity-modes.md](references/fidelity-modes.md) before discussing the planned `multi-view` or `metric` modes.
2. Start with `scenecraft run <project>` and read the resulting run ID, frozen `analysis-request.json`, reference images, active lessons, and `schemas/scene-spec.schema.json` plus the matching object or building schema.
3. As the active Astra agent, inspect the images and write a JSON scene specification inside that run. List critical reference features in an object plan's `required_features`. Do not call the OpenAI API or require an SDK or API key.
4. Submit the plan with `scenecraft resume <project> <run-id> --spec <path> --plan-source astra-agent`. Use `--plan-source manual` only for a plan Astra did not produce from the frozen request.
5. When the run reaches `repair_model`, inspect the stored reference, render, comparison, evaluation, current spec, and repair request. Write a complete revised spec inside a repair artifact conforming to `schemas/repair.schema.json`, then submit it with `scenecraft resume ... --repair <path> --plan-source astra-agent`.
6. Resume the same run after failures; do not create a replacement run merely because an external step failed.
7. Follow [references/workflow.md](references/workflow.md) for evaluation, repair, and completion rules.
8. At `evaluate_fidelity`, inspect the actual images and `visual-review-request.json`. Check every requested feature plus anything missing from the plan. Submit a truthful `visual-review.schema.json` artifact with `resume ... --review <path>`. Bind it to the request's SHA-256. A metrics pass alone never authorizes completion. Reject missing details even when numerical similarity is high.

## Learn

After packaging, enter `learn_from_run` before marking the run complete. Read [references/learning.md](references/learning.md), preserve every lesson in the run report, and apply only validated lessons to later runs. A lesson must name stored before/after iterations; never supply or invent scores. Prefer project memory; promote only generalized, reusable lessons to workflow memory. Finish with `scenecraft complete`, using an explicit no-lessons reason when no reusable improvement occurred.

Failed runs also support `learn` and `note`; `complete` closes their retrospective while preserving failed status. Use `note` for unmeasured observations and setup failures. These remain candidates and cannot activate automatically. Configure a shared store with `scenecraft configure-memory <project> <reviewed-lessons-path>` when reusing generalized lessons across projects.

## Safety and fidelity

- Never execute code returned by a model. Astra produces versioned JSON plans; repository code performs operations.
- Never make a nested model call. The current Astra task is the only reasoning model; SceneCraft’s Python runtime is model-independent.
- Keep paths within the project root and geometry in meters.
- Report unknown scale, hidden faces, occlusions, and invented detail as uncertainty.
- Do not say a model is exact or complete until all declared views pass their thresholds and the evidence is preserved.
- If only one image exists, qualify success as similarity from that declared view, not ground-truth reconstruction of unseen geometry.
- Never execute learned text. Use it only as a scoped planning heuristic or an allowlisted structured parameter.
