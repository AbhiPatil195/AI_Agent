"""
Compatibility shim for legacy launches.

Streamlit scripts previously used `web/app.py`. The app was moved to
`src/ui/app.py`. This wrapper forwards execution so existing shortcuts
or cached URLs keep working.
"""
from __future__ import annotations

import sys
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
SRC = BASE / "src"
TARGET = SRC / "ui" / "app.py"

if not TARGET.exists():
    raise FileNotFoundError(f"Missing target Streamlit app: {TARGET}")

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Importing the module executes the top‑level Streamlit app code.
import ui.app  # noqa: F401

