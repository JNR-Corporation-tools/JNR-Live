from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from threading import Lock

from .security import new_token


@dataclass
class BrowserSession:
    session_id: str
    ip: str
    user_agent: str
    current_url: str
    first_seen: str
    last_activity: str
    revoked: bool = False
    revoked_at: str | None = None
    restored_at: str | None = None


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = Lock()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def touch(self, session_id: str | None, ip: str, user_agent: str, current_url: str) -> tuple[str, BrowserSession]:
        with self._lock:
            sid = session_id or new_token(18)
            now = self._now()
            item = self._sessions.get(sid)
            if item is None:
                item = BrowserSession(
                    sid,
                    ip,
                    user_agent[:240],
                    current_url[:1000],
                    now,
                    now,
                )
                self._sessions[sid] = item
            else:
                item.ip = ip
                item.user_agent = user_agent[:240]
                item.current_url = current_url[:1000]
                item.last_activity = now
            return sid, item

    def touch_existing(self, session_id: str, ip: str, user_agent: str, current_url: str) -> BrowserSession | None:
        with self._lock:
            item = self._sessions.get(session_id)
            if not item or item.revoked:
                return None
            item.ip = ip
            item.user_agent = user_agent[:240]
            item.current_url = current_url[:1000]
            item.last_activity = self._now()
            return item

    def is_revoked(self, session_id: str | None) -> bool:
        if not session_id:
            return False
        with self._lock:
            item = self._sessions.get(session_id)
            return bool(item and item.revoked)

    def revoke(self, session_id: str) -> bool:
        with self._lock:
            item = self._sessions.get(session_id)
            if not item:
                return False
            if not item.revoked:
                item.revoked = True
                item.revoked_at = self._now()
            return True

    def restore(self, session_id: str) -> bool:
        with self._lock:
            item = self._sessions.get(session_id)
            if not item:
                return False
            item.revoked = False
            item.restored_at = self._now()
            return True

    def revoke_all(self) -> int:
        with self._lock:
            changed = 0
            now = self._now()
            for item in self._sessions.values():
                if not item.revoked:
                    item.revoked = True
                    item.revoked_at = now
                    changed += 1
            return changed

    def restore_all(self) -> int:
        with self._lock:
            changed = 0
            now = self._now()
            for item in self._sessions.values():
                if item.revoked:
                    item.revoked = False
                    item.restored_at = now
                    changed += 1
            return changed

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def counts(self, active_seconds: int = 90) -> dict[str, int]:
        rows = self.snapshot(active_seconds)
        return {
            "total": len(rows),
            "active": sum(1 for row in rows if row["active"]),
            "idle": sum(1 for row in rows if row["idle"]),
            "revoked": sum(1 for row in rows if row["revoked"]),
        }

    def snapshot(self, active_seconds: int = 90) -> list[dict]:
        now = datetime.now(timezone.utc)
        with self._lock:
            output = []
            for item in self._sessions.values():
                try:
                    last = datetime.fromisoformat(item.last_activity)
                    age = max(0.0, (now - last).total_seconds())
                except ValueError:
                    age = 999999.0
                row = asdict(item)
                row["active"] = age <= active_seconds and not item.revoked
                row["idle"] = age > active_seconds and not item.revoked
                row["age_seconds"] = round(age, 1)
                output.append(row)
            return sorted(output, key=lambda row: row["last_activity"], reverse=True)

    def active_count(self, active_seconds: int = 90) -> int:
        return self.counts(active_seconds)["active"]
