from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class InsightResult(BaseModel):
    input_path: Path
    summary_md: str
    artifacts: List[Path] = []
    stats: Dict[str, Any] = {}


class DocFormatResult(BaseModel):
    input_path: Path
    output_path: Path
    requested_format: str
    actual_format: str
    warnings: List[str] = []


class AutoNoteEntry(BaseModel):
    ts: str
    topic: str
    message: str


class AutoNoteResult(BaseModel):
    date: str
    appended_path: Path
    summary_path: Path
    topics: Dict[str, int]
    key_points: List[str]


class TaskItem(BaseModel):
    id: int
    title: str
    est_hours: float
    priority: int
    deps: List[int] = []
    status: str = "todo"
    updated_at: Optional[str] = None
    goal: Optional[str] = None


class MediaResult(BaseModel):
    kind: str
    input_path: Path
    json_path: Path
    extra_path: Optional[Path] = None
    metadata: Dict[str, Any] = {}

