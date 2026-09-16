# Set up SceneCraft on a new laptop with Codex

Cloning downloads the workflow, but does not install Python dependencies, Blender, or the Codex plugin. This guide covers all four. The setup agent should perform the steps, verify the results, and leave a local report instead of only describing what to do.

## Start here: the human steps

1. Install the desktop app and sign in with your ChatGPT account. Choose **Codex**, open a local folder where you want the repository, and select **GPT-6 Astra** if available in your account. See the [official quickstart](https://learn.chatgpt.com/docs/quickstart). A browser-only conversation without local execution cannot install software on your laptop.
2. Paste the setup prompt below. You do not need to clone the repository first.
3. Approve the specific downloads, installations, and filesystem access you want. Complete any browser sign-in or operating-system prompts yourself; never paste credentials into a chat.
4. After plugin installation, start a **new local Codex task in the cloned SceneCraft folder** and use the first-model prompt at the end of this guide. New tasks load installed plugin skills; see [official plugin guidance](https://learn.chatgpt.com/docs/plugins).

SceneCraft uses your active Astra task for reasoning. It needs no OpenAI SDK, API key, or separate model service. Account access and usage limits still apply; installing SceneCraft does not grant Astra access. GitHub login is not required to clone a public repository, and GitHub CLI is optional unless you want to contribute or use a private fork.

## Copy-paste setup prompt

```text
Set up SceneCraft on this laptop for reference-image-to-3D modeling:
https://github.com/Igalsr/SceneCraft

Do the installation and verification, not just a plan. Work locally in the
current approved folder; confirm a different destination with me if needed.
Inspect the operating system, CPU architecture, existing Git/Python/Blender,
and Codex plugin support before installing anything.

Clone the repository into a new SceneCraft subfolder if it is absent. If a
checkout already exists, inspect its origin, branch, and changes first;
preserve it and do not reset, overwrite, or switch branches automatically.
Read AGENTS.md, README.md, and docs/new-laptop-setup.md from the checkout,
then follow the setup procedure in that guide.

Use an isolated Python environment and the trusted repository Blender code.
Prefer Python 3.13 and native Blender 5.2.2 LTS for this machine; Blender must
be at least 5.2. Do not downgrade an existing newer version. Ask for approval
before installing system software, changing an existing installation, or
changing Codex plugin configuration. Do not disable security controls.
Use my active GPT-6 Astra Codex task; do not install an OpenAI SDK, ask for
an API key, make a nested model call, or silently substitute another model.

Install SceneCraft and its local Codex marketplace/plugin, then run the
documented checks including real Blender smoke tests. Preserve command
results and a resumable setup checklist under a fresh ignored artifacts/
setup/ directory. Report failed or skipped checks honestly. A successful
doctor check or skipped render tests alone do not mean setup is complete.

Finish with the checkout commit, exact Python and Blender paths, plugin
status, test results, remaining blockers, and a prompt for my first model.
Do not push anything to GitHub or start my real model during setup. Ask me
to start a new task after plugin installation. Do not invent dimensions,
manufacturing requirements, reference features, or visual approval.
```

## Procedure for the setup agent (or manual setup)

### 1. Inspect and clone safely

Detect the host OS, CPU architecture, shell, available disk space, and existing tool versions. Use native binaries for that architecture. If Git or a suitable Python is missing, propose the official installer or an already-installed package manager and obtain the necessary approval. Do not install a package manager merely to avoid asking which installation method the user prefers.

In the approved parent directory, for a **new** checkout only:

```sh
git clone https://github.com/Igalsr/SceneCraft.git SceneCraft
cd SceneCraft
git rev-parse HEAD
git status --short
```

If the destination exists, inspect it instead of cloning over it. Never discard changes. For an explicitly requested update of a clean checkout already on `main` with the expected origin, use `git pull --ff-only origin main`; if it cannot fast-forward, stop and explain. Do not publish any setup files or user assets.

Create a fresh `artifacts/setup/<unique-session-id>/` directory in the checkout. Save command stdout/stderr, exit statuses, and a `setup-report.md` there; update a checklist after each step so another task can resume. Include versions, the repository commit, executable paths, permissions still needed, and test outcomes. These files are ignored by Git. Never log tokens, environment dumps, or credentials. Preserve earlier attempts instead of overwriting their reports.

### 2. Install the Python runtime

Python 3.13 is recommended; CI also tests Python 3.11. Do not use Blender's bundled Python for the SceneCraft CLI. Verify the selected interpreter's version first. The following examples assume it is available under the shown command; use its actual path if necessary.

macOS/Linux:

```sh
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m scenecraft --help
```

Windows PowerShell, with Python 3.13 registered in the Python launcher:

```powershell
py -3.13 --version
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m scenecraft --help
```

Using the environment's Python by explicit path avoids activation and PowerShell execution-policy changes. If `.venv` already exists, inspect and reuse a suitable environment; do not recreate it blindly. The `dev` extra supplies verification tools, not a model SDK. Installing just the plugin does not install this Python runtime or Blender.

### 3. Install or locate Blender

Require **Blender 5.2 or newer**. Prefer the reproducible baseline **Blender 5.2.2 LTS** from the [official Blender release directory](https://download.blender.org/release/Blender5.2/). Select the correct operating system and CPU architecture. Verify downloaded archives against the matching official SHA-256 file before using them. Reuse an existing newer stable version if it passes the smoke tests; do not downgrade it. For a new installation, prefer a versioned download over an unversioned package-manager install. Install side by side with approval if necessary; do not remove someone else's Blender version.

Keep Blender in a persistent installation directory, not a temporary mount or downloads cache. Discover the executable rather than assuming it is on `PATH`:

- macOS: often `/Applications/Blender.app/Contents/MacOS/Blender`; check the actual app location. Use the Apple-silicon build on Apple silicon.
- Linux: the `blender` executable inside the extracted official archive, or a verified existing installation.
- Windows: `blender.exe` inside the actual Blender installation directory; quote paths containing spaces.

Run `scenecraft doctor` through the virtual environment, passing the **actual executable path**:

```sh
.venv/bin/python -m scenecraft doctor --blender "/absolute/path/to/blender"
```

PowerShell equivalent:

```powershell
.\.venv\Scripts\python.exe -m scenecraft doctor --blender "C:\actual\path\blender.exe"
```

Check the returned version, `blender.available`, and `trusted_runner.available`. `doctor` rejects Blender older than 5.2 and unrecognized version output. It does not render a scene or verify your Astra account. Record the actual version; testing a newer release is not a test of the pinned 5.2.2 baseline.

Use the same `--blender` path on later `run`/`resume` commands; the CLI does not persist it automatically. `SCENECRAFT_BLENDER` below is a **test-only setting**, not the CLI's Blender configuration.

Native macOS Apple silicon and Linux x86_64 are the test targets; CI pins Blender 5.2.2 on Linux. Consult the test results for the checkout you installed rather than treating older Blender results as proof. Windows instructions are provided, but this repository has no Windows CI validation; only a successful smoke test on that machine establishes local runtime readiness. The optional Linux x86_64 Docker route is in [sharing.md](sharing.md); native installation is the simpler laptop default.

### 4. Install the Codex plugin

Inspect `codex plugin --help` first. If the command is unavailable, use the app's supported CLI setup or ask the user to update/install a compatible Codex CLI from [official guidance](https://developers.openai.com/codex/cli). Do not assume every Codex version or surface has the same plugin commands, and do not work around an organization's plugin restrictions.

With a compatible Codex CLI, check existing configuration first:

```sh
codex plugin marketplace list
codex plugin list
```

If no conflicting marketplace is registered, register the **absolute checkout root**, not the `plugins/scenecraft` subfolder, then install:

```sh
codex plugin marketplace add "/absolute/path/to/SceneCraft"
codex plugin add scenecraft@scenecraft-workflows
codex plugin list --marketplace scenecraft-workflows
```

Use the actual Windows path in PowerShell. The marketplace manifest is `.agents/plugins/marketplace.json`; the plugin source is `plugins/scenecraft`. If a marketplace with this name already points somewhere else, explain the conflict before changing it. Confirm that SceneCraft is installed and enabled, not merely listed as available. Keep the clone in place: this installation uses a local marketplace.

These commands were checked against the repository author's installed Codex CLI; inspect the new laptop's help output if its version differs. Plugin loading requires a new task/session. The supported plugin surfaces are the desktop app and Codex CLI, not the IDE extension, per [official plugin documentation](https://learn.chatgpt.com/docs/plugins). If Astra or plugin support is unavailable, report that separately from runtime readiness rather than claiming complete setup.

### 5. Verify software and real rendering

From the checkout, on macOS/Linux:

```sh
.venv/bin/python -m ruff check src tests blender scripts
.venv/bin/python scripts/validate_schemas.py
SCENECRAFT_BLENDER="/absolute/path/to/blender" .venv/bin/python -m pytest -q
```

PowerShell:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests blender scripts
.\.venv\Scripts\python.exe scripts/validate_schemas.py
$env:SCENECRAFT_BLENDER = "C:\actual\path\blender.exe"
.\.venv\Scripts\python.exe -m pytest -q
```

Capture the results in the setup report. The tests include actual building and positive-master renders, geometry checks, GLB export, and millimeter STL verification. The initial release has 31 tests; counts may grow. No real Blender test may be skipped in a fully verified setup. With the environment variable unset, two skipped tests are expected and **do not** prove rendering works. Tests use temporary fixtures; their output files are cleaned up, so retain command logs for diagnosis.

If rendering fails, preserve the error and identify the missing dependency, platform limitation, or permission. On Linux, an error about a missing shared library requires the matching OS package, not an arbitrary downloaded library. If a sandbox blocks Blender, request scoped execution approval; do not disable the sandbox globally. Do not rewrite the runner, weaken tests, or fabricate a passing result to complete setup.

For an optional persistent demonstration, run the repository benchmark in a new directory under `artifacts/`:

```sh
.venv/bin/python scripts/benchmark_master.py artifacts/setup-demo-001 --blender "/absolute/path/to/blender"
```

Use another fresh directory if that one exists. The benchmark deliberately stops for actual visual review. Its generated reference tests workflow execution, not reconstruction of an unseen image. Never autoapprove it just to finish installation.

### 6. Handoff and first real model

Return the setup report path and a short checklist: runtime installed, Blender version/path, plugin installed/enabled, full test outcome, account/model confirmation or user action still required. Include the virtual environment's Python path and remind the user to open a **new local task in this checkout**. Do not start a real modeling run until the user supplies its inputs.

Attach or save the reference image generated in the separate ChatGPT conversation. This workflow does not automatically retrieve another chat's images. Provide one primary hero image; optional additional images are supporting evidence in this release.

Paste into the new task, replacing brackets:

```text
Use SceneCraft to make a positive master for pouring silicone around,
not a negative mold. My primary reference is [attached image or local path].
The setup report is [local setup-report.md path].

Target dimensions: [width x depth x height in mm].
Dimensional tolerance: [mm, or ask me].
Minimum feature size: [mm, or ask me].
Intended print/manufacturing process: [details, or unknown].
Mold release strategy: [one-piece / split / cut mold, or discuss with me].

Read the SceneCraft skill and use the hero-view workflow. Before modeling,
resolve missing scale and manufacturing choices with me. Create a new
project under artifacts/projects/ inside this checkout so its project data
stays ignored by Git. Use the verified Python and Blender paths from setup.
Preserve references, render and compare, repair discrepancies, and inspect
every required feature before accepting. Never trade away important shape
details simply to pass image metrics. Record hidden-geometry uncertainty.
Finish with verified exports and the learning phase, including any remaining
physical fabrication checks. Reuse only evidence-supported lessons.
```

For ordinary models, replace `positive master` with `object` and omit mold-specific requirements. The executable mode is currently `hero-view`; `multi-view` and `metric` remain blocked. One image cannot establish unseen geometry or guarantee exact reconstruction. A passing model review is not a certification of printability or silicone release.

## Updates and moving to another laptop

The Git clone transfers the workflow, examples, and curated shared lessons. It **does not** transfer ignored projects, references, runs, deliverables, personal lessons, or machine-specific paths. Back those up privately and preserve their evidence. Run checkpoints contain absolute paths; copying them to another laptop is not a supported portable-resume mechanism. Keep old runs as evidence and start a new project/run on the new machine with deliberately imported references and reviewed lessons.

For workflow updates, preserve local changes, fast-forward only when appropriate, reinstall Python dependencies, and rerun verification. Check plugin installation/version separately: a Git pull alone does not guarantee the cached plugin has refreshed. Use that Codex version's supported reinstall/update flow, then start a new task. Do not delete the clone or existing projects as an update strategy.
