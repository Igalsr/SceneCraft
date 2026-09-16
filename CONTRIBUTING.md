# Contributing

Keep changes artifact-first and reviewable. Astra may propose JSON plans and repairs, but trusted repository code must remain the only code executed by Blender.

Before opening a pull request:

1. Update schemas and tests together when a public artifact changes. Increment the artifact schema version for breaking changes.
2. Preserve failed jobs and evidence; do not overwrite an earlier iteration.
3. Run Ruff, pytest, the JSON Schema validator, and a wheel build.
4. Run the Blender smoke workflow when changing the runner, job contract, geometry generation, materials, cameras, rendering, or exports.
5. Do not commit reference images, generated scenes, private project state, tokens, or secrets unless they are deliberate, licensed public benchmark fixtures.

Pull requests should explain which acceptance or trust invariant changed and include behavioral evidence rather than prompt wording alone.
