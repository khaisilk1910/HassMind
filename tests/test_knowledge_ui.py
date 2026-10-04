"""Include dependency-free JavaScript UI regression checks in unittest discovery."""
from pathlib import Path
import os
import shutil
import subprocess
import unittest


class KnowledgeUITests(unittest.TestCase):
    def test_knowledge_ui_javascript(self):
        node = os.environ.get("NODE_BINARY") or shutil.which("node")
        if not node:
            self.skipTest("Node.js is needed for the UI checks (no npm packages required)")
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [node, "--test", "tests/test_knowledge_ui.js"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
