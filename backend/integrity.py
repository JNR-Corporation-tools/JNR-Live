from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_NAME = "integrity.json"
DEFAULT_PROTECTED = [
    "app.py",
    "config.py",
    "launcher.py",
    "backend/",
    "frontend/",
    "requirements.txt",
]


def _iter_files(root: Path, patterns: list[str]) -> list[Path]:
    found: list[Path] = []
    for pattern in patterns:
        path = root / pattern
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            found.extend(p for p in path.rglob("*") if p.is_file())
    ignored = {"__pycache__", ".venv", ".git"}
    unique: list[Path] = []
    seen: set[str] = set()
    for path in sorted(found):
        if any(part in ignored for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        if rel not in seen and rel != MANIFEST_NAME:
            seen.add(rel)
            unique.append(path)
    return unique


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_manifest(root: Path = ROOT) -> dict[str, Any]:
    files = _iter_files(root, DEFAULT_PROTECTED)
    entries = {p.relative_to(root).as_posix(): sha256_file(p) for p in files}
    return {
        "schema": 1,
        "product": "Live Server",
        "organization": "JNR Corporations",
        "release": "2.1.0",
        "files": entries,
    }


def verify_integrity(root: Path = ROOT) -> dict[str, Any]:
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.exists():
        return {
            "ok": False,
            "status": "missing-manifest",
            "checked": 0,
            "mismatches": [],
            "message": "integrity.json is missing",
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files: dict[str, str] = manifest["files"]
    except (OSError, ValueError, TypeError, KeyError):
        return {
            "ok": False,
            "status": "invalid-manifest",
            "checked": 0,
            "mismatches": [],
            "message": "integrity.json is invalid",
        }

    mismatches = []
    for rel, expected in files.items():
        path = root / rel
        if not path.exists() or not path.is_file():
            mismatches.append({"path": rel, "reason": "missing"})
            continue
        actual = sha256_file(path)
        if actual != expected:
            mismatches.append({"path": rel, "reason": "hash-mismatch"})

    return {
        "ok": not mismatches,
        "status": "verified" if not mismatches else "mismatch",
        "checked": len(files),
        "mismatches": mismatches,
        "message": (
            "Protected project files match the release manifest."
            if not mismatches
            else "Protected project files differ from the release manifest."
        ),
    }
