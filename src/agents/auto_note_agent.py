from __future__ import annotations

import json
import re
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import CFG
from models import AutoNoteResult


STOPWORDS = {
    "the", "and", "to", "of", "in", "a", "for", "is", "on", "that", "with", "as", "by", "it", "at",
    "be", "are", "or", "an", "from", "this", "we", "you", "your", "our", "was", "were", "has", "have",
    "had", "not", "but", "can", "will", "may", "should", "could", "would", "i", "he", "she", "they",
    "them", "their", "there", "here", "been", "into", "over", "per", "via", "about", "than", "then",
}


class AutoNoteAgent:
    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = memory_dir
        self.raw_dir = self.memory_dir / "raw"
        self.sum_dir = self.memory_dir / "summaries"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.sum_dir.mkdir(parents=True, exist_ok=True)

    def add_message(self, message: str, topic: Optional[str] = None) -> AutoNoteResult:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        iso = now.strftime("%Y-%m-%dT%H:%M:%S")

        daily_jsonl = self.raw_dir / f"{date_str}.jsonl"
        masked = self._mask_pii(message)
        rec = {"ts": iso, "topic": (topic or CFG.default_topic), "message": masked}
        with daily_jsonl.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        topics, key_points = self._summarize_day(daily_jsonl)
        summary_md = self._render_summary(date_str, topics, key_points)
        daily_md = self.sum_dir / f"{date_str}.md"
        daily_md.write_text(summary_md, encoding="utf-8")

        self._update_index()

        return AutoNoteResult(date=date_str, appended_path=daily_jsonl, summary_path=daily_md, topics=topics, key_points=key_points)

    def resummarize(self, date_str: Optional[str] = None) -> AutoNoteResult:
        ds = date_str or datetime.now().strftime("%Y-%m-%d")
        daily_jsonl = self.raw_dir / f"{ds}.jsonl"
        topics, key_points = self._summarize_day(daily_jsonl)
        summary_md = self._render_summary(ds, topics, key_points)
        daily_md = self.sum_dir / f"{ds}.md"
        daily_md.write_text(summary_md, encoding="utf-8")
        self._update_index()
        return AutoNoteResult(date=ds, appended_path=daily_jsonl, summary_path=daily_md, topics=topics, key_points=key_points)

    def weekly_summary(self, end_date: Optional[str] = None, iso_week: Optional[str] = None) -> Path:
        # Build weekly summary by ISO week (YYYY-Www) or ending on end_date
        if iso_week:
            y_str, w_str = iso_week.split("-W")
            y, w = int(y_str), int(w_str)
            start = date.fromisocalendar(y, w, 1)
            days = [start + timedelta(days=i) for i in range(7)]
            week_id = iso_week
        else:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.now()
            end_day = end_dt.date()
            start = end_day - timedelta(days=end_day.weekday())
            days = [start + timedelta(days=i) for i in range(7)]
            iso = end_day.isocalendar()
            week_id = f"{iso.year}-W{iso.week:02d}"
        day_strs = [d.strftime("%Y-%m-%d") for d in days]

        agg_topics: Dict[str, int] = {}
        agg_points: Dict[str, int] = {}
        for ds in day_strs:
            jsonl = self.raw_dir / f"{ds}.jsonl"
            topics, key_points = self._summarize_day(jsonl)
            for k, v in topics.items():
                agg_topics[k] = agg_topics.get(k, 0) + v
            for p in key_points:
                agg_points[p] = agg_points.get(p, 0) + 1

        top_points = [p for p, _ in sorted(agg_points.items(), key=lambda kv: (-kv[1], kv[0]))[:10]]
        md_lines = [f"# Weekly Summary — {week_id}", ""]
        if agg_topics:
            md_lines.append("## Topic Totals")
            for k, v in sorted(agg_topics.items(), key=lambda kv: (-kv[1], kv[0])):
                md_lines.append(f"- {k}: {v}")
            md_lines.append("")
        if top_points:
            md_lines.append("## Top Points")
            for p in top_points:
                md_lines.append(f"- {p}")
        else:
            md_lines.append("_(no points)_")
        out = self.sum_dir / f"{week_id}.md"
        out.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
        self._update_index()
        return out

    def list_messages(self, date_str: Optional[str] = None, topic: Optional[str] = None) -> List[Dict[str, str]]:
        ds = date_str or datetime.now().strftime("%Y-%m-%d")
        items = self._read_daily(self.raw_dir / f"{ds}.jsonl")
        if topic:
            t = topic.strip().lower()
            items = [it for it in items if (it.get("topic", "").strip().lower() == t)]
        return items

    # ---------------------------- helpers -----------------------------
    def _read_daily(self, jsonl_path: Path) -> List[Dict[str, str]]:
        items: List[Dict[str, str]] = []
        if not jsonl_path.exists():
            return items
        with jsonl_path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        items.append({
                            "ts": str(obj.get("ts", "")),
                            "topic": str(obj.get("topic", "")),
                            "message": str(obj.get("message", "")),
                        })
                except Exception:
                    continue
        return items

    def _summarize_day(self, jsonl_path: Path) -> Tuple[Dict[str, int], List[str]]:
        items = self._read_daily(jsonl_path)
        topic_counts: Dict[str, int] = {}
        sentences: List[str] = []
        for it in items:
            t = (it.get("topic") or "").strip() or CFG.default_topic
            topic_counts[t] = topic_counts.get(t, 0) + 1
            sentences.extend(self._split_sentences(it.get("message", "")))

        scores = self._score_sentences(sentences)
        seen = set()
        ranked = sorted(range(len(sentences)), key=lambda i: scores.get(i, 0), reverse=True)
        key_points: List[str] = []
        for idx in ranked:
            s = sentences[idx].strip()
            if not s or s.lower() in seen:
                continue
            key_points.append(s)
            seen.add(s.lower())
            if len(key_points) >= 5:
                break
        return topic_counts, key_points

    def _render_summary(self, date_str: str, topics: Dict[str, int], points: List[str]) -> str:
        lines = [f"# Session Summary — {date_str}", ""]
        if topics:
            lines.append("## Topics")
            for k, v in sorted(topics.items(), key=lambda kv: (-kv[1], kv[0])):
                lines.append(f"- {k}: {v}")
            lines.append("")
        if points:
            lines.append("## Key Points")
            for p in points:
                lines.append(f"- {p}")
        else:
            lines.append("_(no key points extracted yet)_")
        return "\n".join(lines) + "\n"

    def _split_sentences(self, text: str) -> List[str]:
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        return [p.strip() for p in parts if p.strip()]

    def _score_sentences(self, sentences: List[str]) -> Dict[int, float]:
        freqs: Dict[str, int] = {}
        sent_tokens: List[List[str]] = []
        for s in sentences:
            tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9_]+", s)]
            tokens = [t for t in tokens if t not in STOPWORDS and len(t) > 2]
            sent_tokens.append(tokens)
            for t in set(tokens):
                freqs[t] = freqs.get(t, 0) + 1
        scores: Dict[int, float] = {}
        if not freqs:
            return scores
        for i, toks in enumerate(sent_tokens):
            score = sum(freqs.get(t, 0) for t in toks)
            scores[i] = float(score)
        return scores

    def _update_index(self) -> None:
        md = ["# AutoNote Index", ""]
        md.append("## Recent Summaries")
        files = sorted(self.sum_dir.glob("*.md"), reverse=True)[:14]
        for p in files:
            md.append(f"- [{p.stem}]({p.name})")
        (self.sum_dir / "index.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    def _mask_pii(self, text: str) -> str:
        email_re = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
        phone_re = re.compile(r"(?:(?:\+\d{1,3}[\s-]?)?(?:\(\d{2,4}\)[\s-]?)?\d{3,4}[\s-]?\d{3,4})")
        text = email_re.sub("[email]", text)
        text = phone_re.sub("[phone]", text)
        return text

