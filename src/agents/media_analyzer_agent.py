from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Dict, Any


try:  # Optional
    from PIL import Image, ExifTags  # type: ignore
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ExifTags = None  # type: ignore

try:  # Optional
    import matplotlib.pyplot as plt  # type: ignore
except Exception:  # pragma: no cover
    plt = None  # type: ignore

try:  # Optional
    from faster_whisper import WhisperModel  # type: ignore
except Exception:  # pragma: no cover
    WhisperModel = None  # type: ignore

import contextlib
import wave


IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}


from models import MediaResult


class MediaAnalyzerAgent:
    def __init__(self, output_dir: Path, transcription: bool = True) -> None:
        self.output_dir = output_dir
        self.enable_transcription = transcription and (WhisperModel is not None)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def analyze(self, input_path: Path) -> MediaResult:
        ext = input_path.suffix.lower()
        if ext in IMAGE_EXT:
            return self._analyze_image(input_path)
        if ext in AUDIO_EXT:
            return self._analyze_audio(input_path)
        # unknown
        data = {
            "type": "unknown",
            "file": str(input_path),
            "size_bytes": input_path.stat().st_size if input_path.exists() else 0,
        }
        jpath = self._json_path(input_path, suffix="unknown.json")
        jpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return MediaResult(kind="unknown", input_path=input_path, json_path=jpath)

    # ----------------------------- image ------------------------------
    def _analyze_image(self, input_path: Path) -> MediaResult:
        meta: Dict[str, Any] = {
            "type": "image",
            "file": str(input_path),
        }

        chart_path: Optional[Path] = None

        if Image is not None:
            try:
                with Image.open(input_path) as im:
                    meta.update(
                        {
                            "format": im.format,
                            "mode": im.mode,
                            "size": {"width": im.width, "height": im.height},
                        }
                    )
                    # EXIF if available
                    exif_data = {}
                    if hasattr(im, "_getexif") and im._getexif():
                        raw_exif = im._getexif() or {}
                        if ExifTags is not None:
                            tag_map = {v: k for k, v in getattr(ExifTags, "TAGS", {}).items()}
                        else:
                            tag_map = {}
                        for k, v in raw_exif.items():
                            name = getattr(ExifTags, "TAGS", {}).get(k, str(k)) if ExifTags else str(k)
                            exif_data[name] = str(v)
                        if exif_data:
                            meta["exif"] = exif_data

                    # Histogram chart per channel (if matplotlib)
                    if plt is not None:
                        try:
                            fig, ax = plt.subplots(figsize=(5, 3))
                            if im.mode in ("RGB", "RGBA"):
                                for i, color in enumerate(["r", "g", "b"]):
                                    hist = im.getchannel(i).histogram()
                                    ax.plot(hist, color=color, label=color.upper())
                                ax.legend()
                            else:
                                hist = im.histogram()
                                ax.plot(hist, color="#4e79a7")
                            ax.set_title("Image Histogram")
                            fig.tight_layout()
                            chart_path = self._extra_path(input_path, suffix="hist.png")
                            fig.savefig(chart_path)
                            plt.close(fig)
                        except Exception:
                            chart_path = None
            except Exception:
                meta["error"] = "Failed to open image"
        else:
            meta["note"] = "Pillow not installed"

        jpath = self._json_path(input_path, suffix="image.json")
        jpath.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return MediaResult(kind="image", input_path=input_path, json_path=jpath, extra_path=chart_path)

    # ----------------------------- audio ------------------------------
    def _analyze_audio(self, input_path: Path) -> MediaResult:
        meta: Dict[str, Any] = {
            "type": "audio",
            "file": str(input_path),
        }
        transcript_path: Optional[Path] = None

        # quick WAV metadata if possible
        if input_path.suffix.lower() == ".wav":
            with contextlib.ExitStack() as stack:
                try:
                    wf = stack.enter_context(wave.open(str(input_path), "rb"))
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    channels = wf.getnchannels()
                    duration = frames / float(rate) if rate else 0.0
                    meta.update({
                        "sample_rate": rate,
                        "channels": channels,
                        "duration_sec": round(duration, 2),
                    })
                except Exception:
                    pass

        # Transcription if faster-whisper is available
        if self.enable_transcription and WhisperModel is not None:
            try:
                model = WhisperModel("small", device="cpu")
                segments, info = model.transcribe(str(input_path))
                lines = [s.text.strip() for s in segments if getattr(s, "text", None)]
                text = "\n".join(lines).strip()
                transcript_path = self._extra_path(input_path, suffix="transcript.txt")
                transcript_path.write_text(text or "", encoding="utf-8")
                meta["transcribed"] = True
                meta["language"] = getattr(info, "language", None)
            except Exception:
                meta["transcribed"] = False
        else:
            meta["note"] = (meta.get("note", "") + " ").strip() + "faster-whisper not installed"

        jpath = self._json_path(input_path, suffix="audio.json")
        jpath.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return MediaResult(kind="audio", input_path=input_path, json_path=jpath, extra_path=transcript_path)

    # ----------------------------- paths ------------------------------
    def _json_path(self, input_path: Path, suffix: str) -> Path:
        return self.output_dir / f"{input_path.stem}_{suffix}"

    def _extra_path(self, input_path: Path, suffix: str) -> Path:
        return self.output_dir / f"{input_path.stem}_{suffix}"
