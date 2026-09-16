# Sharing SceneCraft

Use one Git repository as the source of truth. It keeps the runtime, schemas, trusted Blender code, workflow descriptions, tests, container pin, and Codex plugin versioned together.

## Collaborator setup

Share [the new-laptop setup guide](new-laptop-setup.md), including its copy-paste Codex setup prompt. It covers cloning, isolated dependencies, persistent native Blender, plugin installation, real rendering tests, and the first reference-based model. A clone or plugin installation alone is not sufficient.

After cloning, create a virtual environment, install the project with its development extras, and run scenecraft doctor.

The repository marketplace is `.agents/plugins/marketplace.json` and the plugin source is `plugins/scenecraft`. A collaborator runs `codex plugin marketplace add /absolute/path/to/repository`, then `codex plugin add scenecraft@scenecraft-workflows`, selects Astra, and starts a new task so the skill is loaded. No OpenAI SDK or API credential is required.

## Blender reproducibility

SceneCraft requires Blender 5.2 or newer. The x86_64 container definition pins both the Debian image digest and the official Blender 5.2.2 Linux archive checksum. Build it from the repository root with:

    docker build -t scenecraft-blender:5.2.2 containers/blender-cpu

To use the wrapper, set `SCENECRAFT_PROJECT` to the absolute project directory and pass `--blender /absolute/repository/scripts/docker-blender`. Only that project is mounted writable; the runner repository is mounted read-only.

The CLI accepts an explicit Blender executable path. On Apple silicon, use native macOS Blender; x86_64 emulation can be impractically slow. CPU Cycles is used for portable headless rendering. CI runs unit/contract checks and real Blender building/master smoke tests on pushes and pull requests. Local skipped smoke tests are not renderer validation.

## Data boundaries

Reference stores, `.scenecraft` state/memory, runs, artifacts, and deliverables are ignored at every project depth, including the nested projects in the README. Curated examples require deliberate review; large binaries should use Git LFS or release assets.

Project lessons stay in the project learning directory. Generalized lessons can be reviewed through pull requests in knowledge/lessons.json and selected at runtime by setting SCENECRAFT_WORKFLOW_MEMORY to its absolute path.

Do not promote project names, private image details, secrets, or unverified observations into shared memory.

## Release gate

Before tagging a release:

- run pytest, Ruff, and JSON Schema validation;
- build a wheel and install it into a clean environment;
- run the real Blender smoke test against the pinned version;
- complete at least one reference-to-repair-to-package benchmark and preserve its public evidence;
- confirm the repository license, visibility, and release notes.

The September 2026 synthetic master benchmark is documented in `examples/positive-master/benchmark.md`. It is historical evidence from Blender 4.5.13, not validation of the current Blender baseline. Its reference was rendered from a known specification; it validates repair plumbing and mesh/export checks, not arbitrary-image reconstruction accuracy. Current compatibility must be established by tests on Blender 5.2 or newer.

The repository code is licensed under `0BSD`. Reference images, generated models, and other user-provided project data retain their own applicable rights and are not relicensed merely by being processed with SceneCraft.
