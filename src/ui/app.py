from __future__ import annotations

from pathlib import Path
from datetime import datetime
import re
from typing import Optional
import subprocess
import io
import zipfile
import json
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
    st.header("🧭 Navigation")
    charts_enabled = st.checkbox("Enable charts", value=CFG.enable_charts and have_matplotlib())
    transcribe_enabled = st.checkbox(
        "Enable transcription",
        value=CFG.enable_transcription and have_faster_whisper(),
        help="Requires faster-whisper",
    )
    _choices = {
        "🔎 Insight": "Insight",
        "📝 Formatter": "Formatter",
        "🗒️ AutoNote": "AutoNote",
        "📋 Planner": "Planner",
        "🖼️ Media": "Media",
    }
    sel = st.radio("Choose a tool", list(_choices.keys()))
    page = _choices.get(sel, "Insight")


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
    st.header("🔎 InsightAgent")
    tab_inputs, tab_results, tab_logs = st.tabs(["Inputs", "Results", "Logs"])
    with tab_inputs:
        colL, _ = st.columns([2, 1])

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
            start_ts = datetime.now().timestamp()
            cmd = [
                sys.executable,
                "-m",
                "src.main",
                "insight",
                str(target_path),
            ]
            if not charts_enabled:
                cmd.append("--no-charts")
            st.info("Running: " + " ".join(cmd))
            exp = st.expander("Live Logs", expanded=True)
            log_area = exp.empty()
            logs: list[str] = []
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(BASE),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    bufsize=1,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    logs.append(line.rstrip("\n"))
                    # Keep last 400 lines to avoid huge UI
                    if len(logs) > 400:
                        logs = logs[-400:]
                    log_area.code("\n".join(logs))
                ret = proc.wait()
            except Exception as e:
                logs.append(f"[ui] Error: {e}")
                log_area.code("\n".join(logs))
                ret = -1

            # Locate outputs for this run (best-effort by timestamp)
            try:
                run_root = OUT / "insight"
                md_candidates = sorted(run_root.rglob("*_summary.md"), key=lambda p: p.stat().st_mtime, reverse=True)
                out_dir = None
                for md in md_candidates:
                    if md.stat().st_mtime >= start_ts - 2:
                        out_dir = md.parent
                        break
                if out_dir is None and md_candidates:
                    out_dir = md_candidates[0].parent
                if out_dir is not None:
                    st.session_state["insight_display_dir"] = str(out_dir)
            except Exception:
                pass

            st.session_state["insight_last_run"] = {"path": str(target_path), "ts": datetime.now().isoformat(), "rc": ret}
            st.toast("Insight job completed" if ret == 0 else "Insight job failed", icon="✅" if ret == 0 else "⚠️")

    with tab_results:
        # Show latest run results if available
        disp = st.session_state.get("insight_display_dir")
        if disp:
            out_dir = Path(disp)
            if out_dir.exists():
                st.subheader("Latest Run")
                md_files = list(out_dir.glob("*_summary.md"))
                if md_files:
                    try:
                        st.markdown(md_files[0].read_text(encoding="utf-8", errors="ignore"))
                    except Exception:
                        pass
                imgs = sorted(out_dir.glob("*.png"))
                if imgs:
                    st.caption("Charts")
                    for img in imgs:
                        st.image(str(img), caption=img.name)
                # Offer ZIP download
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for p in out_dir.iterdir():
                        if p.is_file():
                            zf.write(p, arcname=p.name)
                st.download_button(
                    "Download outputs as ZIP",
                    data=buf.getvalue(),
                    file_name=f"insight_{out_dir.name}.zip",
                )
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
    with tab_logs:
        st.caption("Live logs will appear here in the next step.")


def ui_formatter():
    st.header("📝 DocFormatterAgent")
    tab_inputs, tab_results, tab_logs = st.tabs(["Inputs", "Results", "Logs"])
    with tab_inputs:
        colL, _ = st.columns([2, 1])

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
            # Run via CLI and stream logs
            start_ts = datetime.now().timestamp()
            cmd = [
                sys.executable,
                "-m",
                "src.main",
                "docfmt",
                str(temp),
                "--format",
                fmt,
            ]
            if branding:
                cmd += ["--branding", branding]
            st.info("Running: " + " ".join(cmd))
            exp = st.expander("Live Logs", expanded=True)
            log_area = exp.empty()
            logs: list[str] = []
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(BASE),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    bufsize=1,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    logs.append(line.rstrip("\n"))
                    if len(logs) > 400:
                        logs = logs[-400:]
                    log_area.code("\n".join(logs))
                ret = proc.wait()
            except Exception as e:
                logs.append(f"[ui] Error: {e}")
                log_area.code("\n".join(logs))
                ret = -1
            # Locate newest output file
            try:
                out_root = OUT / "docfmt"
                files = [p for p in out_root.rglob("*") if p.is_file()]
                files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                disp = None
                for p in files:
                    if p.stat().st_mtime >= start_ts - 2:
                        disp = p
                        break
                if disp is None and files:
                    disp = files[0]
                if disp is not None:
                    st.session_state["docfmt_display_path"] = str(disp)
            except Exception:
                pass
            st.session_state["docfmt_last_run"] = {"src": str(temp), "ts": datetime.now().isoformat(), "rc": ret}
            st.toast("DocFormatter job completed" if ret == 0 else "DocFormatter job failed", icon="✅" if ret == 0 else "⚠️")
            return
            agent = DocFormatterAgent(templates_dir=TPL, output_dir=OUT / "docfmt")
            res = agent.format(temp, fmt=fmt, branding=branding or None)
            st.success(f"Generated {res.actual_format.upper()} → {Path(res.output_path).name}")
            if res.actual_format == "md":
                st.markdown(Path(res.output_path).read_text(encoding="utf-8", errors="ignore"))
            st.download_button("Download", data=Path(res.output_path).read_bytes(), file_name=Path(res.output_path).name)

    with tab_results:
        disp = st.session_state.get("docfmt_display_path")
        if disp:
            outp = Path(disp)
            if outp.exists():
                st.subheader("Latest Run")
                if outp.suffix.lower() == ".md":
                    try:
                        st.markdown(outp.read_text(encoding="utf-8", errors="ignore"))
                    except Exception:
                        pass
                try:
                    st.download_button("Download output", data=outp.read_bytes(), file_name=outp.name)
                except Exception:
                    st.write(str(outp))
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    zf.write(outp, arcname=outp.name)
                st.download_button("Download as ZIP", data=buf.getvalue(), file_name=f"docfmt_{outp.stem}.zip")
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
    with tab_logs:
        st.caption("Live logs will appear here in the next step.")


def ui_autonote():
    st.header("🗒️ AutoNoteAgent")
    agent = AutoNoteAgent(memory_dir=MEM)
    tab_inputs, tab_results, tab_logs = st.tabs(["Inputs", "Results", "Logs"])
    with tab_inputs:
        colL, _ = st.columns([2, 1])

    with colL:
        msg = st.text_area("Message", height=120)
        topic = st.text_input("Topic", value=CFG.default_topic)
        c1, c2, c3 = st.columns(3)
        if c1.button("Add") and msg:
            start_ts = datetime.now().timestamp()
            cmd = [
                sys.executable,
                "-m",
                "src.main",
                "autonote",
                msg,
            ]
            if topic:
                cmd += ["--topic", topic]
            st.info("Running: " + " ".join(cmd))
            exp = st.expander("Live Logs", expanded=True)
            log_area = exp.empty()
            logs: list[str] = []
            try:
                proc = subprocess.Popen(cmd, cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
                assert proc.stdout is not None
                for line in proc.stdout:
                    logs.append(line.rstrip("\n"))
                    if len(logs) > 400:
                        logs = logs[-400:]
                    log_area.code("\n".join(logs))
                ret = proc.wait()
            except Exception as e:
                logs.append(f"[ui] Error: {e}")
                log_area.code("\n".join(logs))
                ret = -1
            # Find today's summary
            try:
                summ_dir = MEM / "summaries"
                files = [p for p in summ_dir.glob("*.md")]
                files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                disp = None
                for p in files:
                    if p.stat().st_mtime >= start_ts - 2:
                        disp = p
                        break
                if disp is None and files:
                    disp = files[0]
                if disp is not None:
                    st.session_state["autonote_display_path"] = str(disp)
            except Exception:
                pass
            st.toast("Note added" if ret == 0 else "Add failed", icon="✅" if ret == 0 else "⚠️")
        if c2.button("Resummarize Today"):
            start_ts = datetime.now().timestamp()
            cmd = [sys.executable, "-m", "src.main", "autonote", "--resummarize"]
            st.info("Running: " + " ".join(cmd))
            exp = st.expander("Live Logs", expanded=True)
            log_area = exp.empty()
            logs: list[str] = []
            try:
                proc = subprocess.Popen(cmd, cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
                assert proc.stdout is not None
                for line in proc.stdout:
                    logs.append(line.rstrip("\n"))
                    if len(logs) > 400:
                        logs = logs[-400:]
                    log_area.code("\n".join(logs))
                ret = proc.wait()
            except Exception as e:
                logs.append(f"[ui] Error: {e}")
                log_area.code("\n".join(logs))
                ret = -1
            # Capture most recent summary
            try:
                summ_dir = MEM / "summaries"
                files = [p for p in summ_dir.glob("*.md")]
                files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                if files:
                    st.session_state["autonote_display_path"] = str(files[0])
            except Exception:
                pass
            st.toast("Resummarized" if ret == 0 else "Resummarize failed", icon="✅" if ret == 0 else "⚠️")
        if c3.button("Weekly Summary"):
            start_ts = datetime.now().timestamp()
            cmd = [sys.executable, "-m", "src.main", "autonote", "--weekly"]
            st.info("Running: " + " ".join(cmd))
            exp = st.expander("Live Logs", expanded=True)
            log_area = exp.empty()
            logs: list[str] = []
            try:
                proc = subprocess.Popen(cmd, cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
                assert proc.stdout is not None
                for line in proc.stdout:
                    logs.append(line.rstrip("\n"))
                    if len(logs) > 400:
                        logs = logs[-400:]
                    log_area.code("\n".join(logs))
                ret = proc.wait()
            except Exception as e:
                logs.append(f"[ui] Error: {e}")
                log_area.code("\n".join(logs))
                ret = -1
            # Show latest weekly summary written
            try:
                summ_dir = MEM / "summaries"
                files = [p for p in summ_dir.glob("*.md")]
                files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                if files:
                    st.session_state["autonote_display_path"] = str(files[0])
            except Exception:
                pass
            st.toast("Weekly summary done" if ret == 0 else "Weekly failed", icon="✅" if ret == 0 else "⚠️")

    with tab_results:
        disp = st.session_state.get("autonote_display_path")
        if disp:
            p = Path(disp)
            if p.exists():
                st.subheader("Latest Run")
                try:
                    st.markdown(p.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    pass
                try:
                    st.download_button("Download summary", data=p.read_bytes(), file_name=p.name)
                except Exception:
                    st.write(str(p))
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
    with tab_logs:
        st.caption("Live logs will appear here in the next step.")


def ui_planner():
    st.header("📋 TaskPlannerAgent")
    agent = TaskPlannerAgent(store_path=OUT / "tasks.json")
    tab_inputs, tab_results, tab_logs = st.tabs(["Inputs", "Results", "Logs"])
    with tab_inputs:
        colL, _ = st.columns([2, 1])

        with colL:
            goal = st.text_input("Goal")
            c_create, c_list, c_done = st.columns([1, 1, 1])
            status = c_list.selectbox("List status", ["all", "todo", "done"], index=0)
            done_id = c_done.number_input("Done ID", min_value=1, step=1)

            if c_create.button("Create tasks") and goal:
                start_ts = datetime.now().timestamp()
                cmd = [sys.executable, "-m", "src.main", "plan", "create", goal]
                st.info("Running: " + " ".join(cmd))
                exp = st.expander("Live Logs", expanded=True)
                log_area = exp.empty()
                logs: list[str] = []
                try:
                    proc = subprocess.Popen(cmd, cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
                    assert proc.stdout is not None
                    for line in proc.stdout:
                        logs.append(line.rstrip("\n"))
                        if len(logs) > 400:
                            logs = logs[-400:]
                        log_area.code("\n".join(logs))
                    ret = proc.wait()
                except Exception as e:
                    logs.append(f"[ui] Error: {e}")
                    log_area.code("\n".join(logs))
                    ret = -1
                # Load tasks.json
                try:
                    tdb = OUT / "tasks.json"
                    if tdb.exists():
                        st.session_state["planner_tasks_json"] = json.loads(tdb.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    pass
                st.toast("Tasks created" if ret == 0 else "Create failed", icon="✅" if ret == 0 else "⚠️")

            if c_list.button("List"):
                cmd = [sys.executable, "-m", "src.main", "plan", "list", "--status", status]
                st.info("Running: " + " ".join(cmd))
                exp = st.expander("Live Logs", expanded=True)
                log_area = exp.empty()
                logs: list[str] = []
                try:
                    proc = subprocess.Popen(cmd, cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
                    assert proc.stdout is not None
                    for line in proc.stdout:
                        logs.append(line.rstrip("\n"))
                        if len(logs) > 400:
                            logs = logs[-400:]
                        log_area.code("\n".join(logs))
                    ret = proc.wait()
                except Exception as e:
                    logs.append(f"[ui] Error: {e}")
                    log_area.code("\n".join(logs))
                    ret = -1
                try:
                    tdb = OUT / "tasks.json"
                    if tdb.exists():
                        st.session_state["planner_tasks_json"] = json.loads(tdb.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    pass

            if c_done.button("Mark Done"):
                cmd = [sys.executable, "-m", "src.main", "plan", "done", "--id", str(int(done_id))]
                st.info("Running: " + " ".join(cmd))
                exp = st.expander("Live Logs", expanded=True)
                log_area = exp.empty()
                logs: list[str] = []
                try:
                    proc = subprocess.Popen(cmd, cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
                    assert proc.stdout is not None
                    for line in proc.stdout:
                        logs.append(line.rstrip("\n"))
                        if len(logs) > 400:
                            logs = logs[-400:]
                        log_area.code("\n".join(logs))
                    ret = proc.wait()
                except Exception as e:
                    logs.append(f"[ui] Error: {e}")
                    log_area.code("\n".join(logs))
                    ret = -1
                try:
                    tdb = OUT / "tasks.json"
                    if tdb.exists():
                        st.session_state["planner_tasks_json"] = json.loads(tdb.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    pass
                st.toast("Task marked done" if ret == 0 else "Done failed", icon="✅" if ret == 0 else "⚠️")

    with tab_results:
        # Latest tasks view
        tbl = st.session_state.get("planner_tasks_json")
        if isinstance(tbl, list) and tbl:
            try:
                st.subheader("Latest Tasks")
                st.dataframe(tbl, use_container_width=True)
            except Exception:
                pass
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
    with tab_logs:
        st.caption("Live logs will appear here in the next step.")


def ui_media():
    st.header("🖼️ MediaAnalyzerAgent")
    tab_inputs, tab_results, tab_logs = st.tabs(["Inputs", "Results", "Logs"])
    with tab_inputs:
        colL, _ = st.columns([2, 1])

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
            start_ts = datetime.now().timestamp()
            cmd = [sys.executable, "-m", "src.main", "media", str(target_path)]
            st.info("Running: " + " ".join(cmd))
            exp = st.expander("Live Logs", expanded=True)
            log_area = exp.empty()
            logs: list[str] = []
            try:
                proc = subprocess.Popen(cmd, cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
                assert proc.stdout is not None
                for line in proc.stdout:
                    logs.append(line.rstrip("\n"))
                    if len(logs) > 400:
                        logs = logs[-400:]
                    log_area.code("\n".join(logs))
                ret = proc.wait()
            except Exception as e:
                logs.append(f"[ui] Error: {e}")
                log_area.code("\n".join(logs))
                ret = -1
            # Find outputs
            try:
                out_root = OUT / "media"
                jsons = [p for p in out_root.rglob("*.json")]
                jsons.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                disp_json = None
                for p in jsons:
                    if p.stat().st_mtime >= start_ts - 2:
                        disp_json = p
                        break
                if disp_json is None and jsons:
                    disp_json = jsons[0]
                extra = None
                if disp_json:
                    cand_png = disp_json.with_suffix(".png")
                    cand_txt = disp_json.with_suffix(".txt")
                    if cand_png.exists():
                        extra = cand_png
                    elif cand_txt.exists():
                        extra = cand_txt
                if disp_json is not None:
                    st.session_state["media_display_json"] = str(disp_json)
                    st.session_state["media_display_extra"] = str(extra) if extra else None
            except Exception:
                pass
            st.toast("Media analysis complete" if ret == 0 else "Media failed", icon="✅" if ret == 0 else "⚠️")
            return

    with tab_results:
        dj = st.session_state.get("media_display_json")
        if dj:
            p = Path(dj)
            if p.exists():
                st.subheader("Latest Run")
                try:
                    st.json(json.loads(p.read_text(encoding="utf-8", errors="ignore")))
                except Exception:
                    st.code(p.read_text(encoding="utf-8", errors="ignore"), language="json")
                extra = st.session_state.get("media_display_extra")
                if extra:
                    ep = Path(extra)
                    if ep.suffix.lower() == ".png" and ep.exists():
                        st.caption("Histogram")
                        st.image(str(ep))
                    elif ep.suffix.lower() == ".txt" and ep.exists():
                        st.caption("Transcript")
                        st.text(ep.read_text(encoding="utf-8", errors="ignore"))
                # ZIP download
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    zf.write(p, arcname=p.name)
                    if extra and Path(extra).exists():
                        zf.write(Path(extra), arcname=Path(extra).name)
                st.download_button("Download outputs as ZIP", data=buf.getvalue(), file_name=f"media_{p.stem}.zip")
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
    with tab_logs:
        st.caption("Live logs will appear here in the next step.")


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
