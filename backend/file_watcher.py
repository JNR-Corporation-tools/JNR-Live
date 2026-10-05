from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Awaitable, Callable

logger = logging.getLogger("live-server.watcher")

WATCHED_EXTENSIONS = {
    ".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".json", ".svg",
    ".webp", ".png", ".jpg", ".jpeg", ".gif", ".avif", ".ico",
}

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
    WATCHDOG_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - exercised only without optional dependency
    WATCHDOG_AVAILABLE = False
    FileSystemEvent = object

    class FileSystemEventHandler:  # type: ignore[no-redef]
        pass

    Observer = None  # type: ignore[assignment]


class ChangeHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[str, str], None], ignored: list[str]) -> None:
        super().__init__()
        self.callback = callback
        self.ignored = {item.replace("\\", "/").strip("/") for item in ignored if item.strip()}

    def _ignored(self, path: str) -> bool:
        normalized = path.replace("\\", "/")
        parts = Path(normalized).parts
        return any(part in self.ignored for part in parts)

    def _dispatch(self, event: FileSystemEvent) -> None:
        path = getattr(event, "dest_path", None) or event.src_path
        if event.is_directory or self._ignored(path):
            return
        ext = Path(path).suffix.lower()
        if ext not in WATCHED_EXTENSIONS:
            return
        self.callback(str(path), "css" if ext == ".css" else "reload")

    def on_created(self, event: FileSystemEvent) -> None:
        self._dispatch(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._dispatch(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._dispatch(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._dispatch(event)


class FileWatcher:
    def __init__(self, loop: asyncio.AbstractEventLoop, callback: Callable[[str, str], Awaitable[None]]) -> None:
        self.loop = loop
        self.callback = callback
        self.observer = None
        self._poll_thread: threading.Thread | None = None
        self._poll_stop = threading.Event()
        self._lock = threading.Lock()
        self._pending: asyncio.TimerHandle | None = None
        self._pending_paths: set[str] = set()
        self._pending_kind: str | None = None
        self.debounce = 0.12
        self.using_watchdog = False

    def set_debounce_ms(self, value: int) -> None:
        self.debounce = max(0.05, min(value / 1000, 2.0))

    def start(self, root: str, ignored: list[str]) -> None:
        path = Path(root).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"Project directory does not exist: {path}")
        self.stop()
        if WATCHDOG_AVAILABLE:
            handler = ChangeHandler(self._from_thread, ignored)
            observer = Observer()
            observer.schedule(handler, str(path), recursive=True)
            observer.start()
            self.observer = observer
            self.using_watchdog = True
            logger.info("Watching project with watchdog: %s", path)
            return

        ignored_set = {item.replace("\\", "/").strip("/") for item in ignored if item.strip()}
        baseline = self._snapshot(path, ignored_set)
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_worker,
            args=(path, ignored, baseline),
            name="live-server-file-poller",
            daemon=True,
        )
        self._poll_thread.start()
        self.using_watchdog = False
        logger.warning("watchdog is unavailable; using cross-platform fallback polling for %s", path)

    @staticmethod
    def _ignored(path: Path, ignored: set[str]) -> bool:
        return any(part in ignored for part in path.parts)

    def _snapshot(self, root: Path, ignored: set[str]) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        for current, dirs, files in os.walk(root):
            current_path = Path(current)
            dirs[:] = [d for d in dirs if d not in ignored]
            for filename in files:
                path = current_path / filename
                if path.suffix.lower() not in WATCHED_EXTENSIONS or self._ignored(path, ignored):
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                snapshot[str(path)] = (stat.st_mtime_ns, stat.st_size)
        return snapshot

    def _poll_worker(self, root: Path, ignored_list: list[str], baseline: dict[str, tuple[int, int]]) -> None:
        ignored = {item.replace("\\", "/").strip("/") for item in ignored_list if item.strip()}
        previous = baseline
        while not self._poll_stop.wait(0.18):
            current = self._snapshot(root, ignored)
            all_paths = set(previous) | set(current)
            for raw_path in all_paths:
                old = previous.get(raw_path)
                new = current.get(raw_path)
                if old == new:
                    continue
                kind = "css" if Path(raw_path).suffix.lower() == ".css" else "reload"
                self._from_thread(raw_path, kind)
            previous = current

    def _from_thread(self, path: str, kind: str) -> None:
        self.loop.call_soon_threadsafe(self._schedule, path, kind)

    def _schedule(self, path: str, kind: str) -> None:
        with self._lock:
            self._pending_paths.add(path)
            if kind != "css":
                self._pending_kind = "reload"
            elif self._pending_kind != "reload":
                self._pending_kind = "css"
            if self._pending:
                self._pending.cancel()
            self._pending = self.loop.call_later(self.debounce, self._flush)

    def _flush(self) -> None:
        with self._lock:
            paths = list(self._pending_paths)
            kind = self._pending_kind or "reload"
            self._pending_paths.clear()
            self._pending_kind = None
            self._pending = None
        if paths:
            asyncio.create_task(self.callback(paths[0], kind))

    def stop(self) -> None:
        observer = self.observer
        self.observer = None
        if observer:
            observer.stop()
            observer.join(timeout=2)
        if self._poll_thread:
            self._poll_stop.set()
            self._poll_thread.join(timeout=2)
            self._poll_thread = None
        self.using_watchdog = False
        with self._lock:
            if self._pending:
                self._pending.cancel()
                self._pending = None
            self._pending_paths.clear()
            self._pending_kind: str | None = None
        logger.info("File watcher stopped")
