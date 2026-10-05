import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from backend.integrity import generate_manifest, sha256_file, verify_integrity


class IntegrityTests(unittest.TestCase):
    def test_manifest_matches_current_tree(self):
        result = verify_integrity()
        self.assertTrue(result["ok"], result)
        self.assertGreater(result["checked"], 5)

    def test_detects_modified_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = root / "backend"
            frontend = root / "frontend"
            backend.mkdir()
            frontend.mkdir()
            for rel, value in {
                "app.py": "good-app",
                "config.py": "good-config",
                "launcher.py": "good-launcher",
                "backend/demo.py": "good-backend",
                "frontend/demo.js": "good-frontend",
                "requirements.txt": "good-requirements",
            }.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value, encoding="utf-8")

            (root / "integrity.json").write_text(
                json.dumps(generate_manifest(root)), encoding="utf-8"
            )
            self.assertTrue(verify_integrity(root)["ok"])

            (root / "app.py").write_text("tampered", encoding="utf-8")
            result = verify_integrity(root)
            self.assertFalse(result["ok"])
            self.assertEqual(result["mismatches"][0]["path"], "app.py")
            self.assertEqual(len(sha256_file(root / "app.py")), 64)
            self.assertEqual(hashlib.sha256(b"tampered").hexdigest(), sha256_file(root / "app.py"))


if __name__ == "__main__":
    unittest.main()
