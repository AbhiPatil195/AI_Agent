from __future__ import annotations

from pathlib import Path
from datetime import datetime
import re
from typing import Optional
import sys

import streamlit as st

# Ensure `src/` (parent of this ui/) is on sys.path for absolute imports
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from config import CFG  # noqa: E402
from logging_setup import setup_logging  # noqa: E402
from optional import have_matplotlib, have_faster_whisper  # noqa: E402
from paths import OUT, MEM, TPL, BASE, ensure_dirs  # noqa: E402

from agents.insight_agent import InsightAgent
from agents.doc_formatter_agent import DocFormatterAgent
from agents.auto_note_agent import AutoNoteAgent
from agents.task_planner_agent import TaskPlannerAgent
from agents.media_analyzer_agent import MediaAnalyzerAgent


setup_logging()
ensure_dirs()

st.set_page_config(page_title="Agent Suite", layout="wide")
st.title("Agent Suite — Web UI")

with st.sidebar:
    st.header("Settings")
    charts_enabled = st.checkbox("Enable charts", value=CFG.enable_charts and have_matplotlib())
    transcribe_enabled = st.checkbox(
        "Enable transcription",
        value=CFG.enable_transcription and have_faster_whisper(),
        help="Requires faster-whisper",
    )
    page = st.radio("Choose a tool", ["Insight", "Formatter", "AutoNote", "Planner", "Media"])


def save_upload(upload, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / upload.name
    with path.open("wb") as f:
        f.write(upload.getbuffer())
    return path


def _recent_files(root: Path, patterns=("*.png", "*.md", "*.json", "*.pdf", "*.docx"), limit: int = 5):
    files = []
    for pat in patterns:
        files.extend(root.rglob(pat))
    files = [p for p in files if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def ui_insight():
    st.header("InsightAgent")
    colL, colR = st.columns([2, 1])

    with colL:
        uploaded = st.file_uploader("Upload .txt/.log/.csv", type=["txt", "log", "csv"])

        ex_opts, ex_map = [], {}
        for rel in ["examples/logs/example.log", "examples/logs/syslog.log", "examples/data/sample.csv"]:
            p = (BASE / rel)
            if p.exists():
                ex_opts.append(rel)
                ex_map[rel] = p
        ex_sel = st.selectbox("Load example", ["(none)"] + ex_opts, index=0)

        c1, c2 = st.columns(2)
        run = c1.button("Analyze")
        run_ex = c2.button("Analyze example")

        target_path = None
        if run and uploaded is not None:
            target_path = save_upload(uploaded, OUT / "uploads")
        elif run_ex and ex_sel in ex_map:
            import shutil

            src = ex_map[ex_sel]
            dst = (OUT / "uploads" / src.name)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            target_path = dst

        if target_path is not None:
            agent = InsightAgent(output_dir=OUT / "insight", templates_dir=TPL, charts=charts_enabled)
            res = agent.summarize(target_path)
            st.success("Analysis complete.")
            st.subheader("Summary")
            st.markdown(res.summary_md)
            st.subheader("Artifacts")
            for p in res.artifacts:
                if p.suffix.lower() == ".png":
                    st.image(str(p), caption=p.name)
                else:
                    st.write(str(p))

            # Store result for Q&A
            st.session_state["insight_summary"] = res.summary_md
            st.session_state["insight_stats"] = getattr(res, "stats", {})

            st.subheader("Ask about this insight")
            q = st.text_input("Question", placeholder="e.g., How many rows? What are the top HTTP codes?")
            if st.button("Ask") and q:
                ans = _answer_insight(q, st.session_state.get("insight_summary", ""), st.session_state.get("insight_stats", {}))
                st.markdown(ans if ans else "I couldn't find that in the summary.")

    with colR:
        # Latest preview: show first chart and top lines of newest summary
        latest_summary = None
        summaries = list((OUT / "insight").rglob("*_summary.md"))
        if summaries:
            summaries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            latest_summary = summaries[0]
        if latest_summary and latest_summary.exists():
            st.subheader("Latest preview")
            try:
                raw = latest_summary.read_text(encoding="utf-8", errors="ignore")
                snippet = "\n".join(raw.splitlines()[:8])
                # Find first chart in same folder
                img = None
                for p in sorted(latest_summary.parent.glob("*.png")):
                    img = p
                    break
                if img:
                    st.image(str(img), caption=img.name)
                st.markdown(snippet)
            except Exception:
                pass

        st.subheader("Recent outputs")
        recent = _recent_files(OUT / "insight")
        if not recent:
            st.caption("No outputs yet.")
        for p in recent:
            st.write(p.name)
            try:
                st.download_button("Download", data=p.read_bytes(), file_name=p.name, key="ins-" + str(p))
            except Exception:
                st.write(str(p))


def ui_formatter():
    st.header("DocFormatterAgent")
    colL, colR = st.columns([2, 1])

    with colL:
        fmt = st.selectbox("Format", ["md", "docx", "pdf"], index=0)
        branding = st.text_input("Branding (template name)")
        input_mode = st.radio("Input mode", ["Text", "Upload file"], horizontal=True)
        text_content: Optional[str] = None
        src_name = "input"
        if input_mode == "Text":
            text_content = st.text_area("Text/Markdown", height=220)
            ex = BASE / "examples/text/notes.md"
            if ex.exists() and st.button("Load example text"):
                text_content = ex.read_text(encoding="utf-8", errors="ignore")
            src_name = "typed"
        else:
            up = st.file_uploader("Upload .txt or .md", type=["txt", "md"], accept_multiple_files=False)
            if up is not None:
                text_content = up.getvalue().decode("utf-8", errors="ignore")
                src_name = up.name

        if st.button("Format") and text_content:
            temp = OUT / "uploads" / f"ui_{src_name}.md"
            temp.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(text_content, encoding="utf-8")
            agent = DocFormatterAgent(templates_dir=TPL, output_dir=OUT / "docfmt")
            res = agent.format(temp, fmt=fmt, branding=branding or None)
            st.success(f"Generated {res.actual_format.upper()} → {Path(res.output_path).name}")
            if res.actual_format == "md":
                st.markdown(Path(res.output_path).read_text(encoding="utf-8", errors="ignore"))
            st.download_button("Download", data=Path(res.output_path).read_bytes(), file_name=Path(res.output_path).name)

    with colR:
        st.subheader("Recent outputs")
        recent = _recent_files(OUT / "docfmt")
        if not recent:
            st.caption("No outputs yet.")
        for p in recent:
            st.write(p.name)
            try:
                st.download_button("Download", data=p.read_bytes(), file_name=p.name, key="docfmt-" + str(p))
            except Exception:
                st.write(str(p))


def ui_autonote():
    st.header("AutoNoteAgent")
    agent = AutoNoteAgent(memory_dir=MEM)
    colL, colR = st.columns([2, 1])

    with colL:
        msg = st.text_area("Message", height=120)
        topic = st.text_input("Topic", value=CFG.default_topic)
        c1, c2, c3 = st.columns(3)
        if c1.button("Add") and msg:
            res = agent.add_message(msg, topic=topic or None)
            st.success("Saved.")
            st.write(str(res.summary_path))
        if c2.button("Resummarize Today"):
            res = agent.resummarize()
            st.success("Resummarized.")
            st.write(str(res.summary_path))
        if c3.button("Weekly Summary"):
            p = agent.weekly_summary()
            st.success("Weekly written.")
            st.write(str(p))

    with colR:
        st.subheader("Recent summaries")
        summ_dir = MEM / "summaries"
        files = []
        if summ_dir.exists():
            files = [p for p in summ_dir.glob("*.md") if p.name.lower() != "index.md"]
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        # Today's snippet preview
        today = summ_dir / f"{datetime.now().strftime('%Y-%m-%d')}.md"
        preview_path = today if today.exists() else (files[0] if files else None)
        if preview_path and preview_path.exists():
            try:
                raw = preview_path.read_text(encoding="utf-8", errors="ignore")
                snippet = "\n".join([ln for ln in raw.splitlines()[:8]])
                st.caption("Today's summary preview" if preview_path == today else f"Preview: {preview_path.name}")
                st.markdown(snippet)
            except Exception:
                pass
        if not files:
            st.caption("No summaries yet.")
        for p in files[:5]:
            st.write(p.name)
            try:
                st.download_button("Download", data=p.read_bytes(), file_name=p.name, key="note-" + str(p))
            except Exception:
                st.write(str(p))


def ui_planner():
    st.header("TaskPlannerAgent")
    agent = TaskPlannerAgent(store_path=OUT / "tasks.json")
    colL, colR = st.columns([2, 1])

    with colL:
        goal = st.text_input("Goal")
        if st.button("Create tasks") and goal:
            tasks = agent.create_from_goal(goal, append=True)
            st.success(f"Added {len(tasks)} tasks.")
        tasks = agent.list_tasks(status="all")
        if tasks:
            st.dataframe([t.__dict__ for t in tasks], use_container_width=True)

    with colR:
        st.subheader("Tasks DB")
        tdb = OUT / "tasks.json"
        if tdb.exists():
            st.write(f"{tdb.name} • {tdb.stat().st_size} bytes")
            try:
                st.download_button("Download tasks.json", data=tdb.read_bytes(), file_name=tdb.name, key="tasks-json")
            except Exception:
                st.write(str(tdb))
            # Tiny tasks preview
            try:
                preview = agent.list_tasks(status="all")[:5]
                if preview:
                    st.caption("Preview (first tasks)")
                    rows = [
                        {
                            "id": t.id,
                            "title": t.title,
                            "prio": t.priority,
                            "status": t.status,
                            "est_h": getattr(t, "est_hours", None),
                        }
                        for t in preview
                    ]
                    st.table(rows)
            except Exception:
                pass
        else:
            st.caption("No tasks created yet.")


def ui_media():
    st.header("MediaAnalyzerAgent")
    colL, colR = st.columns([2, 1])

    with colL:
        up = st.file_uploader(
            "Upload image or audio",
            type=["png", "jpg", "jpeg", "bmp", "gif", "tiff", "webp", "wav", "mp3", "m4a", "flac", "ogg"],
        )
        ex_opts, ex_map = [], {}
        for rel in ["examples/media/sample.jpg", "examples/media/meeting.wav"]:
            p = (BASE / rel)
            if p.exists():
                ex_opts.append(rel)
                ex_map[rel] = p
        ex_sel = st.selectbox("Load example", ["(none)"] + ex_opts, index=0)
        c1, c2 = st.columns(2)
        run = c1.button("Analyze Media")
        run_ex = c2.button("Analyze example")

        target_path = None
        if run and up is not None:
            target_path = save_upload(up, OUT / "uploads")
        elif run_ex and ex_sel in ex_map:
            import shutil

            src = ex_map[ex_sel]
            dst = (OUT / "uploads" / src.name)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            target_path = dst

        if target_path is not None:
            agent = MediaAnalyzerAgent(output_dir=OUT / "media", transcription=transcribe_enabled)
            res = agent.analyze(target_path)
            st.success("Analysis complete.")
            st.subheader("JSON Report")
            st.code(Path(res.json_path).read_text(encoding="utf-8", errors="ignore"), language="json")
            if res.extra_path and res.extra_path.suffix.lower() == ".png":
                st.subheader("Histogram")
                st.image(str(res.extra_path))
            if res.extra_path and res.extra_path.suffix.lower() == ".txt":
                st.subheader("Transcript")
                st.text(Path(res.extra_path).read_text(encoding="utf-8", errors="ignore"))

    with colR:
        st.subheader("Recent outputs")
        recent = _recent_files(OUT / "media")
        if not recent:
            st.caption("No outputs yet.")
        for p in recent:
            st.write(p.name)
            try:
                st.download_button("Download", data=p.read_bytes(), file_name=p.name, key="med-" + str(p))
            except Exception:
                st.write(str(p))


if page == "Insight":
    ui_insight()
elif page == "Formatter":
    ui_formatter()
elif page == "AutoNote":
    ui_autonote()
elif page == "Planner":
    ui_planner()
else:
    ui_media()


def _answer_insight(question: str, summary_md: str, stats: dict) -> str:
    q = question.strip().lower()
    lines = []

    # Direct stats
    if any(k in q for k in ["row", "rows"]) and ("rows" in stats):
        lines.append(f"Rows: {stats.get('rows')}")
    if any(k in q for k in ["col", "columns"]) and ("cols" in stats):
        lines.append(f"Columns: {stats.get('cols')}")
    if "missing" in q and ("missing_cells" in stats) and ("total_cells" in stats):
        miss = stats.get("missing_cells", 0)
        tot = stats.get("total_cells", 0) or 1
        pct = (miss / tot) * 100.0
        lines.append(f"Missing cells: {miss} / {tot} ({pct:.2f}%)")
    if "http" in q and ("http_code_counts" in stats):
        pairs = sorted(stats.get("http_code_counts", {}).items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        if pairs:
            lines.append("Top HTTP codes: " + ", ".join([f"{k}:{v}" for k, v in pairs]))
    if any(k in q for k in ["level", "error", "warn", "info"]) and ("levels" in stats):
        lv = stats.get("levels", {})
        if lv:
            lines.append("Levels: " + ", ".join([f"{k}:{v}" for k, v in lv.items() if v]))
    if "time" in q and ("first_ts" in stats or "last_ts" in stats):
        lines.append(f"Time range: {stats.get('first_ts') or 'n/a'} → {stats.get('last_ts') or 'n/a'}")

    if lines:
        return "\n".join(["**Answer**:"] + [f"- {ln}" for ln in lines])

    # Fallback: keyword search in summary
    toks = [t for t in re.findall(r"[a-zA-Z0-9_]+", q) if len(t) > 2]
    found = []
    if toks:
        for line in summary_md.splitlines():
            lwr = line.lower()
            if all(t in lwr for t in toks):
                found.append(line)
                if len(found) >= 5:
                    break
    if found:
        return "\n".join(["**Found in summary:**"] + [f"> {ln}" for ln in found])
    return ""
