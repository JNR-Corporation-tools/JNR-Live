from __future__ import annotations

import argparse
import hashlib
import os
import platform
import subprocess
import sys
import venv
from pathlib import Path

from backend.integrity import verify_integrity

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
REQUIRED_MODULES = (
    "fastapi",
    "httpx",
    "qrcode",
    "uvicorn",
    "websockets",
    "watchdog",
    "PIL",
    "psutil",
)
CORE_IMPORT_MODULES = tuple(m for m in REQUIRED_MODULES if m != "watchdog")


class LauncherError(RuntimeError):
    pass


def choose_base_python() -> Path:
    executable = Path(sys.executable).resolve()
    if sys.version_info < (3, 11):
        raise LauncherError(
            f"Python 3.11+ is required. Found {platform.python_version()} at {executable}."
        )
    return executable


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("$", " ".join(str(item) for item in command), flush=True)
    return subprocess.run(command, cwd=ROOT, check=check, text=True)


def ensure_venv(base_python: Path) -> Path:
    target = venv_python()
    if not target.exists():
        print(f"[Live Server] Creating isolated environment for {platform.system()}...", flush=True)
        try:
            builder = venv.EnvBuilder(with_pip=True, clear=False, symlinks=(os.name != "nt"))
            builder.create(VENV)
        except Exception as exc:
            hint = (
                "On Debian/Kali install the venv support with: "
                "sudo apt install python3-venv python3-pip"
                if os.name != "nt"
                else "Install Python 3.11+ from python.org or with Windows package management, then retry."
            )
            raise LauncherError(f"Could not create .venv: {exc}. {hint}") from exc
    if not target.exists():
        raise LauncherError(f"Virtual environment was created but Python was not found at {target}")
    return target


def _requirements_stamp() -> str:
    digest = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    return f"{sys.version_info.major}.{sys.version_info.minor}:{digest}"


def dependencies_ready(python: Path, *, include_optional: bool = True) -> bool:
    modules = REQUIRED_MODULES if include_optional else CORE_IMPORT_MODULES
    script = (
        "import importlib; "
        f"mods={modules!r}; "
        "[importlib.import_module(m) for m in mods]"
    )
    result = subprocess.run(
        [str(python), "-c", script],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
    )
    return result.returncode == 0


def install_dependencies(python: Path, *, force: bool = False) -> None:
    stamp = VENV / ".live-server-deps"
    expected = _requirements_stamp()
    if not force and stamp.exists():
        try:
            if stamp.read_text(encoding="utf-8").strip() == expected and dependencies_ready(python):
                return
        except OSError:
            pass

    print("[Live Server] Installing/repairing Python dependencies...", flush=True)
    result = run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"],
        check=False,
    )
    if result.returncode != 0:
        raise LauncherError(
            "Could not upgrade pip. Check your network connection, proxy settings, "
            "or Python installation."
        )

    result = run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQUIREMENTS)],
        check=False,
    )
    if result.returncode != 0:
        raise LauncherError("Dependency installation failed. See the pip output above.")

    if not dependencies_ready(python):
        missing = []
        for module in REQUIRED_MODULES:
            probe = subprocess.run(
                [str(python), "-c", f"import {module}"],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if probe.returncode != 0:
                missing.append(module)
        detail = ", ".join(missing) or "unknown dependency"
        raise LauncherError(f"Dependencies were installed but these imports still fail: {detail}")

    stamp.write_text(expected + "\n", encoding="utf-8")


def ensure_runtime_dependencies(*, direct_invocation: bool) -> Path:
    """Ensure the isolated runtime exists; optionally re-exec direct app.py runs in it."""
    base_python = choose_base_python()
    target = ensure_venv(base_python)
    current = Path(sys.executable).resolve()
    target_resolved = target.resolve()

    if current == target_resolved:
        install_dependencies(target)
        return target

    if not direct_invocation:
        # Imported by tests/tools: do not mutate the importing interpreter.
        if dependencies_ready(current, include_optional=False):
            return current
        raise LauncherError(
            "Live Server dependencies are missing from the active Python environment. "
            "Run python start.py instead of importing app.py from an unconfigured interpreter."
        )

    install_dependencies(target)
    script = Path(sys.argv[0]).resolve()
    print(f"[Live Server] Switching to isolated runtime: {target}", flush=True)
    os.execv(str(target), [str(target), str(script), *sys.argv[1:]])
    raise AssertionError("os.execv returned unexpectedly")


def print_system_info() -> None:
    print("\nJNR Corporations · Live Server")
    print(f"Platform      : {platform.system()} {platform.release()}")
    print(f"Architecture  : {platform.machine()}")
    print(f"Python        : {platform.python_version()}")
    print(f"Python path   : {sys.executable}")
    print(f"Project       : {ROOT}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-platform installer/launcher for JNR Corporations Live Server")
    parser.add_argument("--no-install", action="store_true", help="Start without installing/repairing dependencies")
    parser.add_argument("--strict-integrity", action="store_true", help="Refuse to start if protected release files were modified")
    args = parser.parse_args()

    try:
        base_python = choose_base_python()
        print_system_info()
        integrity = verify_integrity()
        if args.strict_integrity and not integrity["ok"]:
            details = ", ".join(item["path"] for item in integrity.get("mismatches", []))
            raise LauncherError(f"Integrity check failed. Modified/missing release files: {details or integrity.get("message", "unknown mismatch")}")
        if not integrity["ok"]:
            print(f"[Live Server] Integrity warning: {integrity.get("message", "release files differ")}")
        python = ensure_venv(base_python)
        if not args.no_install:
            install_dependencies(python)
        print("[Live Server] Starting dashboard...", flush=True)
        passthrough = [arg for arg in sys.argv[1:] if arg != "--strict-integrity"]
        return subprocess.call([str(python), str(ROOT / "app.py"), *passthrough], cwd=ROOT)
    except LauncherError as exc:
        print(f"[Live Server] ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[Live Server] Stopped.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
