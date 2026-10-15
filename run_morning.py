#!/usr/bin/env python3
"""Convenience entry point for the self-contained selector."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

if __name__ == "__main__":
    script=Path(__file__).resolve().parent/"standalone_daily.py"
    raise SystemExit(subprocess.run([sys.executable,str(script),*sys.argv[1:]]).returncode)
