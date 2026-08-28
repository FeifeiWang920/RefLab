#!/usr/bin/env python3
"""MF Reflector entry point."""

from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from catia import detect_catia
from ui.main_window import run


def main() -> None:
    # Startup probe (also shown inside the UI)
    status = detect_catia()
    print(f"[CATIA] {status.state.value}: {status.message}")
    run()


if __name__ == "__main__":
    main()
