import asyncio
import tempfile
import unittest
from pathlib import Path

from app import LiveServerApp
from config import Settings


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_settings_rejected(self):
        app = LiveServerApp()
        bad = Settings(interface_ip="127.0.0.1", upstream_host="example.com")
        with self.assertRaises(ValueError):
            app._validate_settings(bad)
        app.lock.release()


    def test_corrupted_huge_pid_is_treated_as_stale(self):
        from app import InstanceLock

        huge_pid = (1 << 200) + 12345
        self.assertFalse(InstanceLock._pid_running(huge_pid))

    async def test_preview_url_is_empty_before_sharing(self):
        app = LiveServerApp()
        self.assertIsNone(app.preview_url)
        app.lock.release()


if __name__ == "__main__":
    unittest.main()
