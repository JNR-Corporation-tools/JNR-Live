from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from threading import Lock


class RingLogHandler(logging.Handler):
    def __init__(self, max_items: int = 300) -> None:
        super().__init__()
        self.items: deque[dict] = deque(maxlen=max_items)
        self.lock2 = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            item = {
                "time": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "message": self.format(record),
            }
            with self.lock2:
                self.items.append(item)
        except Exception:
            pass

    def snapshot(self, limit: int = 200) -> list[dict]:
        with self.lock2:
            return list(self.items)[-limit:]


def configure_logging() -> RingLogHandler:
    handler = RingLogHandler()
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
    return handler
