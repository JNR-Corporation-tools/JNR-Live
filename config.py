from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

APP_NAME = "Live Server"
APP_VERSION = "2.1.0"
APP_ORGANIZATION = "JNR Corporations"
APP_DEVELOPER = "Raj Verma"


@dataclass
class Settings:
    upstream_host: str = "127.0.0.1"
    upstream_port: int = 5500
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8765
    share_port: int = 8787
    interface_ip: str = ""
    project_root: str = ""
    watcher_enabled: bool = True
    reload_debounce_ms: int = 120
    ignored_paths: list[str] = field(
        default_factory=lambda: [
            ".git",
            "node_modules",
            ".venv",
            "__pycache__",
            ".pytest_cache",
            "dist",
            "build",
        ]
    )


class ConfigStore:
    def __init__(self) -> None:
        self.path = Path.home() / ".config" / "live-server" / "config.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            base = asdict(Settings())
            for key in base:
                if key in data:
                    base[key] = data[key]
            return Settings(**base)
        except (OSError, ValueError, TypeError):
            return Settings()

    def save(self, settings: Settings) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
        tmp.replace(self.path)


def settings_from_dict(data: dict[str, Any], current: Settings | None = None) -> Settings:
    old = current or Settings()
    merged = asdict(old)
    for key in merged:
        if key in data:
            merged[key] = data[key]
    return Settings(**merged)
