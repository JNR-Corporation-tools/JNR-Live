import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from backend.file_watcher import FileWatcher


class WatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_css_change_is_debounced(self):
        events = []

        async def callback(path, kind):
            events.append((Path(path).name, kind))

        with tempfile.TemporaryDirectory() as tmp:
            watcher = FileWatcher(asyncio.get_running_loop(), callback)
            watcher.set_debounce_ms(80)
            watcher.start(tmp, ["node_modules", ".git"])
            target = Path(tmp) / "style.css"
            target.write_text("a{color:red}", encoding="utf-8")
            await asyncio.sleep(0.35)
            watcher.stop()

        self.assertTrue(events)
        self.assertEqual(events[-1][1], "css")

    async def test_ignored_path_is_ignored(self):
        events = []

        async def callback(path, kind):
            events.append((path, kind))

        with tempfile.TemporaryDirectory() as tmp:
            node_modules = Path(tmp) / "node_modules"
            node_modules.mkdir()
            watcher = FileWatcher(asyncio.get_running_loop(), callback)
            watcher.set_debounce_ms(70)
            watcher.start(tmp, ["node_modules"])
            target = node_modules / "x.js"
            target.write_text("x", encoding="utf-8")
            await asyncio.sleep(0.25)
            watcher.stop()

        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
