from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple


try:
    import pandas as pd  # type: ignore
except Exception:
    pd = None  # type: ignore

try:
    import matplotlib.pyplot as plt  # type: ignore
except Exception:
    plt = None  # type: ignore

from models import InsightResult as InsightModel
from paths import OUT


class InsightAgent:
    def __init__(self, output_dir: Optional[Path] = None, templates_dir: Optional[Path] = None, charts: bool = True) -> None:
        self.output_dir = output_dir or (OUT / "insight")
        self.templates_dir = templates_dir
        self.charts = charts and (plt is not None)
        self._patterns = self._load_patterns()

    def summarize(self, input_path: Path) -> InsightResult:
        suffix = input_path.suffix.lower()
        if suffix == ".csv":
            return self._summarize_csv(input_path)
        else:
            return self._summarize_text(input_path)

    # ----------------------------- CSV ---------------------------------
    def _summarize_csv(self, input_path: Path) -> InsightModel:
        if pd is None:
            md = self._md_header(input_path) + "\n- pandas not installed; cannot parse CSV.\n"
            return InsightModel(input_path=input_path, summary_md=md, artifacts=[], stats={})

        df, read_note = self._read_csv_robust(input_path)

        rows, cols = df.shape
        md_parts = [self._md_header(input_path)]
        md_parts.append(f"- Type: CSV  | Rows: {rows}  | Cols: {cols}")
        if read_note:
            md_parts.append(f"- Note: {read_note}")

        # Basic missingness
        total_cells = int(rows * cols) if rows and cols else 0
        total_missing = int(df.isna().sum().sum()) if rows and cols else 0
        md_parts.append(f"- Missing cells: {total_missing} / {total_cells}")

        # Numeric summary (first few columns)
        num_cols = list(df.select_dtypes(include="number").columns)
        if num_cols:
            desc = df[num_cols].describe().T.reset_index().rename(columns={"index": "column"})
            md_parts.append("\n### Numeric Summary (first 6)\n")
            md_parts.append(self._md_table(desc.head(6), max_cols=7))

        # Categorical summary (limit to meaningful columns)
        cat_section, cat_cols_used = self._categorical_summary(df)
        if cat_section:
            md_parts.append("\n### Categorical Summary\n")
            md_parts.append(cat_section)

        artifacts: list[Path] = []
        out_dir = self._artifact_dir(input_path)

        # Histogram for first numeric
        if self.charts and num_cols:
            first = num_cols[0]
            try:
                fig, ax = plt.subplots(figsize=(5, 3))
                df[first].dropna().plot(kind="hist", bins=20, ax=ax, title=f"Histogram: {first}")
                ax.set_xlabel(first)
                fig.tight_layout()
                chart_path = out_dir / f"{input_path.stem}_hist.png"
                fig.savefig(chart_path)
                plt.close(fig)
                artifacts.append(chart_path)
                md_parts.append(f"\n![hist]({chart_path.as_posix()})\n")
            except Exception:
                pass

        # Correlation heatmap
        if self.charts and len(num_cols) >= 2:
            try:
                corr = df[num_cols].corr(numeric_only=True)
                fig, ax = plt.subplots(figsize=(5, 4))
                im = ax.imshow(corr.values, cmap="Blues", vmin=-1, vmax=1)
                ax.set_xticks(range(len(num_cols)))
                ax.set_yticks(range(len(num_cols)))
                ax.set_xticklabels(num_cols, rotation=45, ha="right", fontsize=8)
                ax.set_yticklabels(num_cols, fontsize=8)
                ax.set_title("Correlation")
                fig.colorbar(im, ax=ax, shrink=0.8)
                fig.tight_layout()
                cpath = out_dir / f"{input_path.stem}_corr.png"
                fig.savefig(cpath)
                plt.close(fig)
                artifacts.append(cpath)
                md_parts.append(f"\n![corr]({cpath.as_posix()})\n")
            except Exception:
                pass

        stats = {
            "rows": rows,
            "cols": cols,
            "missing_cells": total_missing,
            "total_cells": total_cells,
            "numeric_cols": num_cols[:10],
            "categorical_cols": cat_cols_used,
        }

        return InsightModel(input_path=input_path, summary_md="\n".join(md_parts), artifacts=artifacts, stats=stats)

    # ---------------------------- TEXT/LOG ------------------------------
    def _summarize_text(self, input_path: Path) -> InsightModel:
        stats, samples = self._scan_text_file(input_path)

        md_parts = [self._md_header(input_path)]
        md_parts.append("- Type: text/log")
        md_parts.append(f"- Lines: {stats['lines']}  | Words: {stats['words']}  | Bytes: {stats['bytes']}")

        # Time range if any
        if stats.get("first_ts") or stats.get("last_ts"):
            first = stats.get("first_ts")
            last = stats.get("last_ts")
            md_parts.append(f"- Time range: {first or 'n/a'} → {last or 'n/a'}")

        # Error counts
        if stats.get("levels"):
            parts = [f"{k}:{v}" for k, v in stats["levels"].items() if v]
            if parts:
                md_parts.append("- Levels: " + ", ".join(parts))

        # HTTP status
        if stats.get("http_errors"):
            md_parts.append(f"- HTTP 4xx/5xx hits: {stats['http_errors']}")

        # Sample lines
        if samples:
            md_parts.append("\n### Sample Error Lines\n")
            for label, lines in samples.items():
                if not lines:
                    continue
                md_parts.append(f"- {label} (first {len(lines)}):")
                for ln in lines:
                    md_parts.append(f"  - `{ln}`")

        artifacts = []
        if self.charts and stats.get("levels"):
            try:
                fig, ax = plt.subplots(figsize=(5, 3))
                items = list(stats["levels"].items())
                labels = [k for k, _ in items]
                values = [v for _, v in items]
                ax.bar(labels, values, color="#4e79a7")
                ax.set_title("Log Level Counts")
                fig.tight_layout()
                out_dir = self._artifact_dir(input_path)
                chart_path = out_dir / f"{input_path.stem}_levels.png"
                fig.savefig(chart_path)
                plt.close(fig)
                artifacts.append(chart_path)
                md_parts.append(f"\n![chart]({chart_path.as_posix()})\n")
            except Exception:
                pass

        # Timeline chart (per minute or per second)
        if self.charts and stats.get("timeline_min"):
            try:
                t_items = sorted(stats["timeline_min"].items())
                xs = [dt for dt, _ in t_items]
                ys = [cnt for _, cnt in t_items]
                if len(xs) <= 1 and stats.get("timeline_sec"):
                    t_items = sorted(stats["timeline_sec"].items())
                    xs = [dt for dt, _ in t_items]
                    ys = [cnt for _, cnt in t_items]
                if len(xs) > 1:
                    fig, ax = plt.subplots(figsize=(6, 3))
                    ax.plot(xs, ys, marker="o", linewidth=1)
                    ax.set_title("Events Over Time")
                    ax.set_xlabel("Time")
                    ax.set_ylabel("Count")
                    fig.autofmt_xdate()
                    out_dir = self._artifact_dir(input_path)
                    t_path = out_dir / f"{input_path.stem}_timeline.png"
                    fig.savefig(t_path)
                    plt.close(fig)
                    artifacts.append(t_path)
                    md_parts.append(f"\n![timeline]({t_path.as_posix()})\n")
            except Exception:
                pass

        # Per-level timelines
        if self.charts and stats.get("timeline_min_levels"):
            try:
                series = stats["timeline_min_levels"]
                all_minutes = sorted({m for lvl in series.values() for m in lvl.keys()})
                if len(all_minutes) > 1:
                    fig, ax = plt.subplots(figsize=(6, 3))
                    for lvl_name, counts in series.items():
                        ys = [counts.get(m, 0) for m in all_minutes]
                        ax.plot(all_minutes, ys, marker="o", linewidth=1, label=lvl_name)
                    ax.set_title("Per-level Timeline")
                    ax.set_xlabel("Time")
                    ax.set_ylabel("Count")
                    ax.legend(loc="upper left", fontsize=8)
                    fig.autofmt_xdate()
                    out_dir = self._artifact_dir(input_path)
                    t2_path = out_dir / f"{input_path.stem}_timeline_levels.png"
                    fig.savefig(t2_path)
                    plt.close(fig)
                    artifacts.append(t2_path)
                    md_parts.append(f"\n![timeline-levels]({t2_path.as_posix()})\n")
            except Exception:
                pass

        # HTTP status code counts table (top)
        if stats.get("http_code_counts"):
            rows = sorted(stats["http_code_counts"].items(), key=lambda kv: (-kv[1], kv[0]))[:10]
            if rows:
                md_parts.append("\n### HTTP Status Codes (top)\n")
                md_lines = ["| code | count |", "| --- | ---: |"]
                for code, cnt in rows:
                    md_lines.append(f"| {code} | {cnt} |")
                md_parts.append("\n" + "\n".join(md_lines) + "\n")

        # Artifacts links
        if artifacts:
            md_parts.append("\n### Artifacts\n")
            for p in artifacts:
                md_parts.append(f"- [{p.name}]({p.as_posix()})")

        return InsightModel(input_path=input_path, summary_md="\n".join(md_parts), artifacts=artifacts, stats=stats)

    # ----------------------------- Helpers -----------------------------
    def _scan_text_file(self, path: Path) -> Tuple[Dict[str, Any], Dict[str, Iterable[str]]]:
        levels = Counter()
        http_errors = 0
        http_code_counts = Counter()
        lines = 0
        words = 0
        bytes_ = path.stat().st_size
        first_ts: Optional[str] = None
        last_ts: Optional[str] = None

        lvl_map: Dict[str, re.Pattern] = self._patterns.get("levels", {})
        ts_patterns = self._patterns.get("timestamps", [])
        http_re: Optional[re.Pattern] = self._patterns.get("http_error")

        sample_keys = set([k for k in lvl_map.keys() if k.upper() in {"ERROR", "WARNING", "CRITICAL", "EXCEPTION"}])
        if "Exception" in lvl_map:
            sample_keys.add("Exception")
        err_samples: Dict[str, list[str]] = {k: [] for k in sample_keys} or {"Exception": []}

        timeline_min: Dict[datetime, int] = defaultdict(int)
        timeline_sec: Dict[datetime, int] = defaultdict(int)
        timeline_min_levels: Dict[str, Dict[datetime, int]] = defaultdict(lambda: defaultdict(int))

        with path.open("r", errors="ignore") as f:
            for raw in f:
                s = raw.rstrip("\n")
                lines += 1
                words += len(s.split())

                # timestamps (try multiple patterns)
                dt_found: Optional[datetime] = None
                ts_display: Optional[str] = None
                for spec in ts_patterns:
                    rx = spec.get("rx")
                    fmt = spec.get("format")
                    infer = bool(spec.get("infer_year"))
                    if rx is None or fmt is None:
                        continue
                    m = rx.search(s)
                    if not m:
                        continue
                    ts_str = m.group(0)
                    dt = self._parse_timestamp(ts_str, fmt, infer)
                    if dt is not None:
                        dt_found = dt
                        ts_display = dt.strftime("%Y-%m-%d %H:%M:%S")
                        break
                if dt_found is not None:
                    if first_ts is None:
                        first_ts = ts_display
                    last_ts = ts_display
                    timeline_sec[dt_found.replace(microsecond=0)] += 1
                    timeline_min[dt_found.replace(second=0, microsecond=0)] += 1

                # levels
                matched_levels = []
                for name, rx in lvl_map.items():
                    if rx.search(s):
                        levels[name] += 1
                        matched_levels.append(name)
                        if name in err_samples and len(err_samples[name]) < 3:
                            err_samples[name].append(s[:200])

                # http status
                if http_re is not None:
                    _m = http_re.findall(s)
                    if _m:
                        http_errors += 1
                        for _code in _m:
                            try:
                                if isinstance(_code, tuple):
                                    _code = _code[0]
                                _code = str(_code)
                                if _code.startswith(("4", "5")):
                                    http_code_counts[_code] += 1
                            except Exception:
                                pass

                # per-level minute timeline
                if dt_found is not None and 'matched_levels' in locals() and matched_levels:
                    _minute = dt_found.replace(second=0, microsecond=0)
                    for _lvl in matched_levels:
                        timeline_min_levels[_lvl][_minute] += 1

        stats: Dict[str, Any] = {
            "lines": lines,
            "words": words,
            "bytes": bytes_,
            "http_errors": http_errors,
            "http_code_counts": dict(http_code_counts),
            "levels": dict(levels),
            "first_ts": first_ts or "",
            "last_ts": last_ts or "",
            "timeline_min": dict(timeline_min),
            "timeline_sec": dict(timeline_sec),
            "timeline_min_levels": {k: dict(v) for k, v in timeline_min_levels.items()},
        }
        return stats, err_samples

    def _parse_timestamp(self, s: str, fmt: str, infer_year: bool = False) -> Optional[datetime]:
        ss = s.strip()
        try:
            dt = datetime.strptime(ss, fmt)
            # If format omitted year (e.g., syslog), strptime sets year=1900
            if infer_year and dt.year == 1900:
                now = datetime.now()
                dt = dt.replace(year=now.year)
            return dt
        except Exception:
            # small special-case: allow 'T' in ISO formats by normalizing
            if 'T' in ss and "%Y-%m-%d %H:%M:%S" in fmt:
                try:
                    ss2 = ss.replace('T', ' ')
                    dt = datetime.strptime(ss2, "%Y-%m-%d %H:%M:%S")
                    return dt
                except Exception:
                    return None
            return None

    def _md_header(self, path: Path) -> str:
        return f"# Summary for {path.name}\n\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    def _md_table(self, df, max_cols: int = 6) -> str:  # type: ignore[no-redef]
        try:
            cols = list(df.columns)[:max_cols]
            lines = ["| " + " | ".join(map(str, cols)) + " |",
                     "| " + " | ".join(["---"] * len(cols)) + " |"]
            for _, row in df.iloc[:8].iterrows():
                vals = [str(row[c]) for c in cols]
                lines.append("| " + " | ".join(vals) + " |")
            return "\n" + "\n".join(lines) + "\n"
        except Exception:
            return "\n_(table unavailable)_\n"

    def _artifact_dir(self, input_path: Path) -> Path:
        d = self.output_dir / input_path.stem
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ----------------------------- CSV helpers -----------------------------
    def _read_csv_robust(self, path: Path):
        note = ""
        encodings = ["utf-8", "cp1252", "latin-1"]
        seps = [None, ",", ";", "\t", "|"]
        for enc in encodings:
            for sep in seps:
                try:
                    df = pd.read_csv(path, sep=sep, encoding=enc, engine="python")
                    return df, (note or (f"encoding={enc}, sep={'auto' if sep is None else sep}"))
                except Exception:
                    continue
        # last resort empty
        try:
            return pd.DataFrame(), "empty or unreadable CSV"
        except Exception:
            return pd.DataFrame(), "empty"

    def _categorical_summary(self, df: 'pd.DataFrame'):
        try:
            cats = []
            used_cols = []
            # Identify candidate categorical columns
            for col in df.columns:
                if len(used_cols) >= 3:
                    break
                s = df[col]
                # Skip IDs or long free-text columns
                if str(col).lower() in {"name", "id", "uuid"}:
                    continue
                if s.dtype == 'O' or str(s.dtype).startswith('category'):
                    nunique = s.nunique(dropna=True)
                    avg_len = s.dropna().astype(str).str.len().mean() if len(s.dropna()) else 0
                    if nunique <= 20 and avg_len <= 20:
                        top = s.astype("string").value_counts(dropna=True).head(5)
                        for v, c in top.items():
                            cats.append({"column": col, "value": str(v), "count": int(c)})
                        used_cols.append(col)
                # Cabin prefix special-case
                if str(col).lower() == "cabin":
                    pref = s.dropna().astype(str).str[0]
                    top = pref.value_counts().head(5)
                    for v, c in top.items():
                        cats.append({"column": f"{col}_prefix", "value": str(v), "count": int(c)})
                    if col not in used_cols:
                        used_cols.append(col)
            if not cats:
                return "", []
            import pandas as _pd
            tdf = _pd.DataFrame(cats)
            # Render grouped by column
            sections = []
            for col in tdf["column"].unique():
                sections.append(f"#### {col}")
                sect = tdf[tdf["column"] == col][["value", "count"]]
                sections.append(self._md_table(sect))
            return "\n".join(sections), used_cols
        except Exception:
            return "", []

    def _load_patterns(self) -> Dict[str, Any]:
        # Load configurable regex patterns; provide sensible defaults
        defaults = {
            "timestamps": [
                {"regex": r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\b", "format": "%Y-%m-%d %H:%M:%S"}
            ],
            "levels": {
                "ERROR": r"\bERROR\b",
                "WARNING": r"\bWARN(?:ING)?\b",
                "CRITICAL": r"\bCRITICAL\b",
                "INFO": r"\bINFO\b",
                "Exception": r"\bException\b|Traceback",
            },
            "http_error": r"\b([45]\d{2})\b",
        }
        cfg = defaults
        tpl = self.templates_dir / "log_patterns.json" if self.templates_dir else None
        if tpl and tpl.exists():
            try:
                cfg = json.loads(tpl.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                cfg = defaults

        # compile timestamps (support both legacy 'timestamp' and list 'timestamps')
        compiled: Dict[str, Any] = {}
        ts_specs = []
        if "timestamps" in cfg and isinstance(cfg["timestamps"], list):
            ts_specs = cfg["timestamps"]
        elif "timestamp" in cfg:  # legacy single pattern
            ts_specs = [{"regex": cfg.get("timestamp"), "format": "%Y-%m-%d %H:%M:%S"}]
        else:
            ts_specs = defaults["timestamps"]

        compiled_ts = []
        for spec in ts_specs:
            try:
                rx = re.compile(spec.get("regex", defaults["timestamps"][0]["regex"]), re.IGNORECASE)
                fmt = spec.get("format", "%Y-%m-%d %H:%M:%S")
                infer = bool(spec.get("infer_year", False))
                compiled_ts.append({"rx": rx, "format": fmt, "infer_year": infer})
            except Exception:
                continue
        compiled["timestamps"] = compiled_ts

        # compile levels
        lvl_cfg = cfg.get("levels", defaults["levels"]) or {}
        compiled_lvls: Dict[str, re.Pattern] = {}
        for name, pattern in lvl_cfg.items():
            try:
                compiled_lvls[name] = re.compile(pattern, re.IGNORECASE)
            except Exception:
                continue
        compiled["levels"] = compiled_lvls

        # http errors
        try:
            compiled["http_error"] = re.compile(cfg.get("http_error", defaults["http_error"]))
        except Exception:
            compiled["http_error"] = re.compile(defaults["http_error"])  # type: ignore
        return compiled
