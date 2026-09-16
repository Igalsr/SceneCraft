from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from .contracts import validate_scene_spec
from .errors import WorkerError
from .protocol import JobRequest, JobResult
from .util import read_json, resolve_inside, sha256_file


@dataclass(frozen=True)
class BlenderInfo:
    executable: str | None
    available: bool
    version: str | None = None
    error: str | None = None


def trusted_runner_path() -> Path:
    source_runner = Path(__file__).resolve().parents[2] / "blender" / "runner.py"
    if source_runner.is_file():
        return source_runner
    bundled = resources.files("scenecraft").joinpath("resources/blender_runner.py")
    return Path(str(bundled))


class BlenderWorker:
    def __init__(
        self,
        executable: str = "blender",
        runner: Path | None = None,
        *,
        timeout_seconds: int = 900,
    ):
        self.executable = executable
        self.runner = (runner or trusted_runner_path()).resolve()
        self.timeout_seconds = timeout_seconds

    def doctor(self) -> BlenderInfo:
        resolved = shutil.which(self.executable)
        if resolved is None and Path(self.executable).is_file():
            resolved = str(Path(self.executable).resolve())
        if resolved is None:
            return BlenderInfo(None, False, error=f"Blender executable not found: {self.executable}")
        try:
            completed = subprocess.run(
                [resolved, "--version"], capture_output=True, text=True,
                check=False, timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return BlenderInfo(resolved, False, error=str(exc))
        first_line = (completed.stdout or completed.stderr).splitlines()
        return BlenderInfo(
            resolved,
            completed.returncode == 0,
            version=first_line[0] if first_line else None,
            error=None if completed.returncode == 0 else completed.stderr.strip(),
        )

    def command(self, job_path: Path) -> list[str]:
        info = self.doctor()
        if not info.available or not info.executable:
            raise WorkerError(info.error or "Blender is unavailable")
        if not self.runner.is_file():
            raise WorkerError(f"Trusted Blender runner not found: {self.runner}")
        return [
            info.executable, "--background", "--factory-startup", "--python",
            str(self.runner), "--", "--job", str(job_path.resolve()),
        ]

    def run(self, job_path: Path, log_path: Path) -> JobResult:
        job = JobRequest.load(job_path)
        root = Path(job.workspace_root).resolve()
        validate_scene_spec(read_json(Path(job.inputs["building_spec"])))
        try:
            resolve_inside(root, log_path)
        except ValueError as exc:
            raise WorkerError(str(exc)) from exc
        result_path = Path(job.outputs["result"])
        # Preserve the complete previous attempt, including partial outputs and logs.
        previous = [Path(path) for path in job.outputs.values()] + [log_path]
        if any(path.exists() for path in previous):
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            token = uuid.uuid4().hex[:8]
            archive = result_path.parent / "attempts" / f"{stamp}-{token}"
            archive.mkdir(parents=True)
            shutil.copyfile(job_path, archive / "job.json")
            for path in previous:
                if path.is_file():
                    relative = path.relative_to(root)
                    target = archive / "workspace" / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    path.replace(target)
        command = []
        try:
            command = self.command(job_path)
            completed = subprocess.run(
                command, capture_output=True, text=True, check=False,
                timeout=self.timeout_seconds,
            )
            stdout, stderr = completed.stdout, completed.stderr
            return_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return_code = -1
            self._write_log(log_path, command, stdout, stderr, "timeout")
            JobResult(job_id=job.job_id, status="failed", error="Worker timeout").save(result_path)
            raise WorkerError(f"Blender exceeded the {self.timeout_seconds}-second timeout") from exc
        except (OSError, WorkerError) as exc:
            self._write_log(log_path, command, "", str(exc), "launch-failed")
            JobResult(job_id=job.job_id, status="failed", error=str(exc)).save(result_path)
            raise WorkerError(str(exc)) from exc
        self._write_log(log_path, command, stdout, stderr, str(return_code))
        if not result_path.is_file():
            JobResult(job_id=job.job_id, status="failed", error=f"Blender exited {return_code} without a result artifact").save(result_path)
            raise WorkerError(f"Blender exited {return_code} without a result artifact")
        result = JobResult.load(result_path)
        if result.job_id != job.job_id:
            raise WorkerError(
                f"Worker result job_id {result.job_id!r} does not match {job.job_id!r}"
            )
        if return_code != 0 or result.status != "succeeded":
            raise WorkerError(result.error or f"Blender worker exited {return_code}")
        artifacts = {artifact["name"]: artifact for artifact in result.artifacts}
        expected_names = set(job.outputs) - {"result"}
        if set(artifacts) != expected_names:
            raise WorkerError(
                f"Worker artifacts {sorted(artifacts)} do not match expected {sorted(expected_names)}"
            )
        for name, artifact in artifacts.items():
            path = Path(artifact["path"])
            try:
                resolve_inside(root, path)
            except ValueError as exc:
                raise WorkerError(str(exc)) from exc
            if path.resolve() != Path(job.outputs[name]).resolve():
                raise WorkerError(f"Worker artifact {name} does not match its declared output path")
            if not path.is_file():
                raise WorkerError(f"Worker artifact is missing: {path}")
            if sha256_file(path) != artifact["sha256"]:
                raise WorkerError(f"Worker artifact digest mismatch: {path}")
        return result

    @staticmethod
    def _write_log(
        log_path: Path,
        command: list[str],
        stdout: str,
        stderr: str,
        outcome: str,
    ) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"COMMAND: {shlex.join(command)}\nOUTCOME: {outcome}\n\n"
            f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}",
            encoding="utf-8",
        )


def python_runtime() -> str:
    return f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
