import tempfile
import unittest
from pathlib import Path

from scenecraft.errors import SceneCraftError
from scenecraft.project import Project
from tests.helpers import make_reference


class ProjectTests(unittest.TestCase):
    def test_create_and_deduplicate_decoded_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "house"
            source = Path(temporary) / "reference.png"
            make_reference(source)
            project = Project.create(root, "Courtyard House")
            first = project.add_reference(source, "primary", "hero")
            second = project.add_reference(source, "primary", "hero")
            self.assertEqual(first, second)
            self.assertEqual(first["width"], 128)
            self.assertEqual(first["format"], "png")
            self.assertTrue((root / first["file"]).is_file())

    def test_signature_only_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            source = temporary / "broken.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\nnot-an-image")
            project = Project.create(temporary / "project", "Broken House")
            with self.assertRaises(SceneCraftError):
                project.add_reference(source, "primary", "hero")


if __name__ == "__main__":
    unittest.main()
