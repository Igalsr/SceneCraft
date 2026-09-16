# SceneCraft repository guidance

- Treat files under `inputs/references/` as immutable evidence. Import a replacement instead of editing an existing reference.
- Treat JSON schemas in `schemas/` as public contracts; update tests and the schema version for breaking changes.
- Astra may propose structured plans and repairs, but only trusted repository code may execute inside Blender.
- Never execute model-generated Python or shell text.
- Every external step must write a result artifact and leave a resumable checkpoint.
- Keep geometry in meters and preserve semantic object names and collections.
- A run may claim success only when every required view passes its declared acceptance thresholds.
- Preserve failed runs and evidence for diagnosis; do not silently overwrite them.
- Preserve every run lesson, but activate it automatically only when measured improvement and no required-view regression support it.
- Treat learned instructions as scoped heuristics. Current reference evidence and explicit user requirements take precedence.
- Never turn a learned lesson into executable Python or shell text; learning may change structured plans and allowlisted parameters only.
- Use the active GPT-6 Astra Codex task for reasoning. Do not require an OpenAI SDK, API key, or nested model call.

## New-machine setup

When asked to install or set up SceneCraft, follow `docs/new-laptop-setup.md`. Preserve existing environments and projects, keep setup logs under a fresh ignored `artifacts/setup/` directory, and distinguish runtime verification from plugin/model availability. Never report skipped Blender tests as verified rendering. Setup does not authorize pushing to GitHub or starting a user's real model.
