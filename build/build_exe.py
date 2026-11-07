#!/usr/bin/env python3
"""Kept for old instructions: builds the portable dist\\JARVIS folder (no installer).

Use build/build_installer.py (or build_installer.bat) for the full installer.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_installer import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["--no-installer"] + sys.argv[1:]))
