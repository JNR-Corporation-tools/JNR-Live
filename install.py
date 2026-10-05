"""Install dependencies for the current OS without starting the dashboard."""
from __future__ import annotations

import platform
import sys

from launcher import choose_base_python, ensure_venv, install_dependencies, print_system_info

if __name__ == "__main__":
    try:
        print_system_info()
        python = ensure_venv(choose_base_python())
        install_dependencies(python, force=True)
        print(f"\n[Live Server] Setup complete for {platform.system()}.")
        print("Start with: python start.py")
    except Exception as exc:
        print(f"[Live Server] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
