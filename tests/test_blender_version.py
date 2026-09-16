import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scenecraft.errors import WorkerError
from scenecraft.worker import BlenderWorker


class BlenderVersionTests(unittest.TestCase):
    def probe(self, output, returncode=0, stderr=""):
        with patch("scenecraft.worker.shutil.which", return_value="/test/blender"), patch(
            "scenecraft.worker.subprocess.run",
            return_value=subprocess.CompletedProcess([], returncode, output, stderr),
        ):
            return BlenderWorker().doctor()

    def test_accepts_minimum_patch_and_newer_versions(self):
        for version in ("5.2.0", "5.2.2", "5.10.0", "6.0.0"):
            with self.subTest(version=version):
                info = self.probe(f"Blender {version}\n\tbuild date: example\n")
                self.assertTrue(info.available, info.error)
                self.assertEqual(info.version, f"Blender {version}")

    def test_rejects_older_versions(self):
        for version in ("4.5.13", "5.0.0", "5.1.99"):
            with self.subTest(version=version):
                info = self.probe(f"Blender {version}\n")
                self.assertFalse(info.available)
                self.assertIn("requires Blender 5.2.0 or newer", info.error)

    def test_rejects_unknown_or_missing_version(self):
        for output in ("", "Python 3.13.0\n", "Blender unknown\n"):
            with self.subTest(output=output):
                info = self.probe(output)
                self.assertFalse(info.available)
                self.assertIn("Cannot verify Blender version", info.error)

    def test_nonzero_exit_is_not_treated_as_compatible(self):
        info = self.probe("Blender 5.2.2\n", returncode=1, stderr="launch failed")
        self.assertFalse(info.available)
        self.assertEqual(info.error, "launch failed")

    def test_build_command_rejects_unsupported_runtime(self):
        info = self.probe("Blender 4.5.13\n")
        with (
            patch.object(BlenderWorker, "doctor", return_value=info),
            self.assertRaisesRegex(WorkerError, "requires Blender 5.2.0"),
        ):
            BlenderWorker().command(Path("unused-job.json"))
