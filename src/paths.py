from __future__ import annotations

from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
SRC = BASE / "src"
OUT = SRC / "output"
MEM = SRC / "memory"
TPL = SRC / "templates"


def ensure_dirs() -> None:
    for p in [OUT, MEM, TPL, OUT / "logs", OUT / "insight", OUT / "docfmt", OUT / "media", OUT / "uploads"]:
        p.mkdir(parents=True, exist_ok=True)

