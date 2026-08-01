import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)


class ImplicitInvocationTests(unittest.TestCase):
    def test_router_is_absent_from_ordinary_codex_skill_catalog(self) -> None:
        codex = shutil.which("codex")
        if codex is None:
            self.skipTest("Codex CLI is unavailable")

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            codex_home = temporary / "codex"
            project = temporary / "project"
            project.mkdir()
            destination = codex_home / "skills" / "gsd-path"
            destination.parent.mkdir(parents=True)
            shutil.copytree(PROJECT_ROOT / "skills" / "gsd-path", destination)

            environment = os.environ.copy()
            environment["CODEX_HOME"] = str(codex_home)
            result = subprocess.run(
                [codex, "debug", "prompt-input", "please update this project"],
                cwd=project,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            prompt_input = json.loads(result.stdout)
            skill_catalogs = [text for text in strings(prompt_input) if "<skills_instructions>" in text]
            self.assertTrue(skill_catalogs)
            self.assertNotIn("- gsd-path:", skill_catalogs[0])


if __name__ == "__main__":
    unittest.main()
