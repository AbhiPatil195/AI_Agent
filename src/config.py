from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    timezone: str = os.getenv("APP_TIMEZONE", "Asia/Kolkata")
    default_topic: str = os.getenv("APP_DEFAULT_TOPIC", "general")
    enable_charts: bool = os.getenv("APP_ENABLE_CHARTS", "1") not in {"0", "false", "False"}
    enable_transcription: bool = os.getenv("APP_ENABLE_TRANSCRIPTION", "1") not in {"0", "false", "False"}


CFG = Config()

