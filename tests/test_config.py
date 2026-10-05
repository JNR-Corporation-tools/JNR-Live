import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import ConfigStore, Settings, settings_from_dict


class ConfigTests(unittest.TestCase):
    def test_settings_defaults(self):
        s = Settings()
        self.assertEqual(s.upstream_port, 5500)
        self.assertEqual(s.share_port, 8787)

    def test_settings_merge(self):
        s = settings_from_dict({"upstream_port": 5510, "watcher_enabled": False}, Settings())
        self.assertEqual(s.upstream_port, 5510)
        self.assertFalse(s.watcher_enabled)
        self.assertEqual(s.share_port, 8787)

    def test_store_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            with patch.object(ConfigStore, "__init__", lambda self: setattr(self, "path", path)):
                store = ConfigStore()
                original = Settings(upstream_port=5599, project_root=tmp)
                store.save(original)
                loaded = store.load()
                self.assertEqual(loaded.upstream_port, 5599)
                self.assertEqual(loaded.project_root, tmp)


if __name__ == "__main__":
    unittest.main()
