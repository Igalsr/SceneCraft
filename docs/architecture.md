# Architecture

SceneCraft separates reasoning, validation, and execution.

1. Reference intake decodes each image, records dimensions and a SHA-256 digest, and copies it into the immutable evidence store.
2. A run snapshots project settings, the reference manifest, and applicable validated lessons.
3. The active GPT-6 Astra task inspects those artifacts and proposes a building specification. SceneCraft itself makes no model API call.
4. The runtime rejects unknown fields, non-finite numbers, unsafe paths, and invalid geometry before writing a trusted Blender job.
5. Blender builds architectural solids or general objects from allowlisted primitives and explicit mesh data. Object operands support union/difference; positive masters additionally receive a geometry report and an STL with millimeter coordinates.
6. The runtime verifies the result identity, output locations, file existence, and every SHA-256 before advancing.
7. The hero render is compared with the locked primary reference using silhouette IoU, tolerant edge F1, perceptual similarity, and hard scene checks.
8. Failed metrics produce a repair request. Passing metrics require a recorded visual review bound to the exact evidence request. Missing reference details reject the iteration even when numerical similarity passes. Astra returns a revised specification and the runtime creates a new iteration.
9. Only an accepted iteration is packaged. The learning phase then compares stored evaluation artifacts and can activate a lesson only when the aggregate improves without a required metric regression.

## Checkpoint layout

Each run uses a generated, validated identifier. Its directory contains frozen inputs, plans, repairs, per-iteration Blender jobs, per-iteration evidence, learning artifacts, and state.json.

Before another worker execution, previous job outputs and logs are moved into a unique `attempts/` archive. Process launch errors, timeouts and missing worker results emit failure artifacts. Evaluation can resume from recorded results without rebuilding. Reference and frozen-configuration hashes are checked at every consequential phase.

## Completion gates

A successful run requires all of the following:

- every declared hero-view threshold passes;
- every required visual feature has a passing observation and there are no outstanding review issues;
- positive-master geometry passes the declared solid/dimension checks, with manual process review;
- native scene, interchange scene, render, scene manifest, and evaluation artifacts pass integrity checks;
- accepted artifacts and repair provenance are copied into a run-specific deliverable package, whose complete manifest is re-hashed at completion;
- the learning report contains at least one recorded lesson or an explicit no-lessons reason.

When the iteration budget is exhausted, the run fails and records the best evaluation pointer while retaining all evidence.

Failed runs may record measured lessons or unmeasured candidate notes. Their retrospective closeout does not change failure to success. Shared memory is selected explicitly per project; only validated lessons are included automatically in future analysis requests.

## Security boundary

Astra can write only JSON data. It cannot supply Python, shell, Blender expressions, or arbitrary operation names. Blender receives the repository-owned runner and a strict job contract whose paths must stay under the project root. The worker validates result identity and hashes before the state machine advances.

## Current scope

The hero-view mode is executable. Multi-view and metric modes are represented for forward compatibility but blocked at run time. A hero-view acceptance result means similarity from that camera—not proof of unseen structure or real-world dimensions.
