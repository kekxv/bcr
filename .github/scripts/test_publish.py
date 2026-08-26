import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS))

from publish import generate_registry_index  # noqa: E402
from registry import RegistryClient  # noqa: E402


class GenerateRegistryIndexTest(unittest.TestCase):
    def test_root_registry_contains_only_empty_mirrors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            modules_dir = Path(temp_dir) / "modules" / "example"
            modules_dir.mkdir(parents=True)
            (modules_dir / "metadata.json").write_text(
                '{"versions": ["1.0.0"]}\n', encoding="utf-8"
            )

            registry_index = generate_registry_index(RegistryClient(temp_dir))

        self.assertEqual(registry_index, {"mirrors": []})


if __name__ == "__main__":
    unittest.main()
