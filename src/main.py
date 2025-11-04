import argparse
import sys
from pathlib import Path

from logging_setup import setup_logging, install_global_excepthook
from paths import OUT, TPL, MEM, ensure_dirs

from agents.insight_agent import InsightAgent
from agents.doc_formatter_agent import DocFormatterAgent
from agents.auto_note_agent import AutoNoteAgent
from agents.task_planner_agent import TaskPlannerAgent
from agents.media_analyzer_agent import MediaAnalyzerAgent


def _ensure_dirs(base: Path) -> None:
    ensure_dirs()


def cmd_insight(args: argparse.Namespace) -> int:
    ipath = Path(args.input)
    if not ipath.exists():
        print(f"Input not found: {ipath}")
        return 2
    agent = InsightAgent(output_dir=OUT / "insight", templates_dir=TPL, charts=(not getattr(args, 'no_charts', False)))
    result = agent.summarize(ipath)

    # Write markdown summary
    md_dir = OUT / "insight" / ipath.stem
    md_dir.mkdir(parents=True, exist_ok=True)
    md_path = md_dir / f"{ipath.stem}_summary.md"
    md_path.write_text(result.summary_md, encoding="utf-8")
    print(f"Summary written: {md_path}")
    return 0


def cmd_docfmt(args: argparse.Namespace) -> int:
    ipath = Path(args.input)
    if not ipath.exists():
        print(f"Input not found: {ipath}")
        return 2
    agent = DocFormatterAgent(templates_dir=TPL, output_dir=OUT / "docfmt")
    res = agent.format(ipath, fmt=args.format, branding=getattr(args, "branding", None))
    if res.actual_format != res.requested_format:
        print(f"Requested {res.requested_format}, fell back to {res.actual_format}.")
    print(f"Report written: {res.output_path}")
    return 0


def cmd_autonote(args: argparse.Namespace) -> int:
    agent = AutoNoteAgent(memory_dir=MEM)
    if args.resummarize:
        res = agent.resummarize(getattr(args, "date", None))
        print(f"Resummarized: {res.summary_path}")
        return 0
    if args.weekly:
        p = agent.weekly_summary(end_date=getattr(args, "date", None), iso_week=getattr(args, "iso_week", None))
        print(f"Weekly summary: {p}")
        return 0
    if getattr(args, "list", False):
        items = agent.list_messages(date_str=getattr(args, "date", None), topic=getattr(args, "topic", None))
        if not items:
            print("No messages found.")
            return 0
        for it in items:
            print(f"{it['ts']} [{it.get('topic','')}] {it['message']}")
        return 0
    if not args.message:
        print("Provide a message or use --resummarize/--weekly")
        return 2
    res = agent.add_message(args.message, topic=getattr(args, "topic", None))
    print(f"Saved message to: {res.appended_path}")
    print(f"Updated summary: {res.summary_path}")
    if res.topics:
        print("Topics:", ", ".join(f"{k}:{v}" for k,v in res.topics.items()))
    if res.key_points:
        print("Key points:")
        for p in res.key_points:
            print(" -", p)
    return 0


def cmd_plan_create(args: argparse.Namespace) -> int:
    store = OUT / "tasks.json"
    agent = TaskPlannerAgent(store_path=store)
    tasks = agent.create_from_goal(args.goal, append=True)
    print(f"Added {len(tasks)} tasks for goal: {args.goal}")
    for t in tasks:
        est = getattr(t, 'estimate_min', None)
        if est is None and hasattr(t, 'est_hours'):
            est_str = f"{getattr(t, 'est_hours')}h"
        else:
            est_str = f"{est}m"
        print(f"[{t.id}] (P{t.priority}, {est_str}) {t.title}")
    print(f"Store: {store}")
    return 0


def cmd_plan_list(args: argparse.Namespace) -> int:
    base = Path(__file__).resolve().parents[1]
    out_dir = base / "src" / "output"
    store = out_dir / "tasks.json"
    agent = TaskPlannerAgent(store_path=store)
    tasks = agent.list_tasks(status=args.status)
    if not tasks:
def cmd_plan_list(args: argparse.Namespace) -> int:
    store = OUT / "tasks.json"
    agent = TaskPlannerAgent(store_path=store)
    tasks = agent.list_tasks(status=args.status)
    if not tasks:
        print("No tasks saved yet.")
        return 0
    for t in tasks:
        mark = "\u2713" if t.status == "done" else " "
        est = getattr(t, 'estimate_min', None)
        if est is None and hasattr(t, 'est_hours'):
            est_str = f"{getattr(t, 'est_hours')}h"
        else:
            est_str = f"{est}m"
        print(f"[{t.id}] [{mark}] P{t.priority} {est_str} - {t.title}")
    print(f"Store: {store}")
    return 0
    out_dir = base / "src" / "output"
    store = out_dir / "tasks.json"
    agent = TaskPlannerAgent(store_path=store)
    t = agent.mark_done(args.id)
    if not t:
        print(f"Task id not found: {args.id}")
        return 1
    print(f"Marked done: [{t.id}] {t.title}")
    return 0


def cmd_media(args: argparse.Namespace) -> int:
    ipath = Path(args.input)
    if not ipath.exists():
        print(f"Input not found: {ipath}")
        return 2
    base = Path(__file__).resolve().parents[1]
    out_dir = base / "src" / "output"
    agent = MediaAnalyzerAgent(output_dir=out_dir)
    res = agent.analyze(ipath)
    print(f"Kind: {res.kind}")
    print(f"JSON: {res.json_path}")
    if res.extra_path:
        print(f"Extra: {res.extra_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-cli",
        description="Multi-agent CLI: insight, docfmt, autonote, plan, media",
    )
    parser.add_argument("--version", action="version", version="agent-cli 0.1.0")

    sub = parser.add_subparsers(dest="command")

    p_insight = sub.add_parser("insight", help="Summarize logs/txt/csv quickly")
    p_insight.add_argument("input", type=str, help="Path to .txt/.log/.csv file")
    p_insight.set_defaults(func=cmd_insight)

    p_doc = sub.add_parser("docfmt", help="Format text into MD/DOCX/PDF")
    p_doc.add_argument("input", type=str, help="Path to input text/markdown file")
    p_doc.add_argument("--format", choices=["md", "docx", "pdf"], default="md")
    p_doc.add_argument("--branding", type=str, help="Branding template name (without .json)")
    p_doc.set_defaults(func=cmd_docfmt)

    p_note = sub.add_parser("autonote", help="Append message and update daily summary")
    p_note.add_argument("message", nargs="?", type=str, help="Message text to capture")
    p_note.add_argument("--topic", type=str, help="Optional topic tag")
    p_note.add_argument("--resummarize", action="store_true", help="Recompute today's summary (no message required)")
    p_note.add_argument("--weekly", action="store_true", help="Generate weekly summary ending today")
    p_note.set_defaults(func=cmd_autonote)

    p_plan = sub.add_parser("plan", help="Task planner operations")
    sub_plan = p_plan.add_subparsers(dest="plan_cmd")

    p_plan_create = sub_plan.add_parser("create", help="Create tasks from goal")
    p_plan_create.add_argument("goal", type=str, help="Describe your goal")
    p_plan_create.set_defaults(func=cmd_plan_create)

    p_plan_list = sub_plan.add_parser("list", help="List tasks")
    p_plan_list.add_argument("--status", choices=["todo", "done", "all"], default="todo")
    p_plan_list.set_defaults(func=cmd_plan_list)

    p_plan_done = sub_plan.add_parser("done", help="Mark a task done")
    p_plan_done.add_argument("--id", type=int, required=True, help="Task ID to mark done")
    p_plan_done.set_defaults(func=cmd_plan_done)

    p_media = sub.add_parser("media", help="Analyze image/audio")
    p_media.add_argument("input", type=str, help="Path to image/audio file")
    p_media.set_defaults(func=cmd_media)

    return parser


def main(argv=None) -> int:
    base = Path(__file__).resolve().parents[1]
    _ensure_dirs(base)

    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
import argparse
import sys
from pathlib import Path

from logging_setup import setup_logging, install_global_excepthook
from paths import OUT, TPL, MEM, ensure_dirs

from agents.insight_agent import InsightAgent
from agents.doc_formatter_agent import DocFormatterAgent
from agents.auto_note_agent import AutoNoteAgent
from agents.task_planner_agent import TaskPlannerAgent
from agents.media_analyzer_agent import MediaAnalyzerAgent


def _ensure_dirs(base: Path) -> None:
    ensure_dirs()


def cmd_insight(args: argparse.Namespace) -> int:
    ipath = Path(args.input)
    if not ipath.exists():
        print(f"Input not found: {ipath}")
        return 2
    agent = InsightAgent(output_dir=OUT / "insight", templates_dir=TPL, charts=(not getattr(args, 'no_charts', False)))
    result = agent.summarize(ipath)

    md_dir = OUT / "insight" / ipath.stem
    md_dir.mkdir(parents=True, exist_ok=True)
    md_path = md_dir / f"{ipath.stem}_summary.md"
    md_path.write_text(result.summary_md, encoding="utf-8")
    print(f"Summary written: {md_path}")
    return 0


def cmd_docfmt(args: argparse.Namespace) -> int:
    ipath = Path(args.input)
    if not ipath.exists():
        print(f"Input not found: {ipath}")
        return 2
    agent = DocFormatterAgent(templates_dir=TPL, output_dir=OUT / "docfmt")
    res = agent.format(ipath, fmt=args.format, branding=getattr(args, "branding", None))
    if res.actual_format != res.requested_format:
        print(f"Requested {res.requested_format}, fell back to {res.actual_format}.")
    print(f"Report written: {res.output_path}")
    return 0


def cmd_autonote(args: argparse.Namespace) -> int:
    agent = AutoNoteAgent(memory_dir=MEM)
    if getattr(args, "resummarize", False):
        res = agent.resummarize()
        print(f"Resummarized: {res.summary_path}")
        return 0
    if getattr(args, "weekly", False):
        p = agent.weekly_summary()
        print(f"Weekly summary: {p}")
        return 0
    if not args.message:
        print("Provide a message or use --resummarize/--weekly")
        return 2
    res = agent.add_message(args.message, topic=getattr(args, "topic", None))
    print(f"Saved message to: {res.appended_path}")
    print(f"Updated summary: {res.summary_path}")
    if res.topics:
        print("Topics:", ", ".join(f"{k}:{v}" for k, v in res.topics.items()))
    if res.key_points:
        print("Key points:")
        for p in res.key_points:
            print(" -", p)
    return 0


def cmd_plan_create(args: argparse.Namespace) -> int:
    store = OUT / "tasks.json"
    agent = TaskPlannerAgent(store_path=store)
    tasks = agent.create_from_goal(args.goal, append=True)
    print(f"Added {len(tasks)} tasks for goal: {args.goal}")
    for t in tasks:
        est = getattr(t, 'estimate_min', None)
        if est is None and hasattr(t, 'est_hours'):
            est_str = f"{getattr(t, 'est_hours')}h"
        else:
            est_str = f"{est}m"
        print(f"[{t.id}] (P{t.priority}, {est_str}) {t.title}")
    print(f"Store: {store}")
    return 0


def cmd_plan_list(args: argparse.Namespace) -> int:
    store = OUT / "tasks.json"
    agent = TaskPlannerAgent(store_path=store)
    tasks = agent.list_tasks(status=args.status, blocked=getattr(args, 'blocked', False), today=getattr(args, 'today', False))
    if not tasks:
        print("No tasks saved yet.")
        return 0
    for t in tasks:
        mark = "\u2713" if t.status == "done" else " "
        est = getattr(t, 'estimate_min', None)
        if est is None and hasattr(t, 'est_hours'):
            est_str = f"{getattr(t, 'est_hours')}h"
        else:
            est_str = f"{est}m"
        print(f"[{t.id}] [{mark}] P{t.priority} {est_str} - {t.title}")
    print(f"Store: {store}")
    return 0


def cmd_plan_done(args: argparse.Namespace) -> int:
    store = OUT / "tasks.json"
    agent = TaskPlannerAgent(store_path=store)
    t = agent.mark_done(args.id)
    if not t:
        print(f"Task id not found: {args.id}")
        return 1
    print(f"Marked done: [{t.id}] {t.title}")
    return 0


def cmd_media(args: argparse.Namespace) -> int:
    ipath = Path(args.input)
    if not ipath.exists():
        print(f"Input not found: {ipath}")
        return 2
    agent = MediaAnalyzerAgent(output_dir=OUT / "media")
    res = agent.analyze(ipath)
    print(f"Kind: {res.kind}")
    print(f"JSON: {res.json_path}")
    if res.extra_path:
        print(f"Extra: {res.extra_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-cli",
        description="Multi-agent CLI: insight, docfmt, autonote, plan, media",
    )
    parser.add_argument("--version", action="version", version="agent-cli 0.1.0")

    sub = parser.add_subparsers(dest="command")

    p_insight = sub.add_parser("insight", help="Summarize logs/txt/csv quickly")
    p_insight.add_argument("input", type=str, help="Path to .txt/.log/.csv file")
    p_insight.add_argument("--no-charts", action="store_true", help="Disable chart generation")
    p_insight.set_defaults(func=cmd_insight)

    p_doc = sub.add_parser("docfmt", help="Format text into MD/DOCX/PDF")
    p_doc.add_argument("input", type=str, help="Path to input text/markdown file")
    p_doc.add_argument("--format", choices=["md", "docx", "pdf"], default="md")
    p_doc.add_argument("--branding", type=str, help="Branding template name (without .json)")
    p_doc.set_defaults(func=cmd_docfmt)

    p_note = sub.add_parser("autonote", help="Append message and update daily summary")
    p_note.add_argument("message", nargs="?", type=str, help="Message text to capture")
    p_note.add_argument("--topic", type=str, help="Optional topic tag")
    p_note.add_argument("--resummarize", action="store_true", help="Recompute summary; use --date to target a day")
    p_note.add_argument("--weekly", action="store_true", help="Generate weekly summary; use --iso-week or --date")
    p_note.add_argument("--date", type=str, help="Date YYYY-MM-DD for resummarize or weekly end date")
    p_note.add_argument("--iso-week", dest="iso_week", type=str, help="ISO week like 2025-W45 for weekly")
    p_note.add_argument("--list", action="store_true", help="List messages (optionally filter by --topic/--date)")
    p_note.set_defaults(func=cmd_autonote)

    p_plan = sub.add_parser("plan", help="Task planner operations")
    sub_plan = p_plan.add_subparsers(dest="plan_cmd")

    p_plan_create = sub_plan.add_parser("create", help="Create tasks from goal")
    p_plan_create.add_argument("goal", type=str, help="Describe your goal")
    p_plan_create.set_defaults(func=cmd_plan_create)

    p_plan_list = sub_plan.add_parser("list", help="List tasks")
    p_plan_list.add_argument("--status", choices=["todo", "done", "all"], default="todo")
    p_plan_list.add_argument("--blocked", action="store_true", help="Show tasks blocked by dependencies")
    p_plan_list.add_argument("--today", action="store_true", help="Show today's focus tasks (P1 todo)")
    p_plan_list.set_defaults(func=cmd_plan_list)

    p_plan_done = sub_plan.add_parser("done", help="Mark a task done")
    p_plan_done.add_argument("--id", type=int, required=True, help="Task ID to mark done")
    p_plan_done.set_defaults(func=cmd_plan_done)

    p_media = sub.add_parser("media", help="Analyze image/audio")
    p_media.add_argument("input", type=str, help="Path to image/audio file")
    p_media.set_defaults(func=cmd_media)

    return parser


def main(argv=None) -> int:
    setup_logging()
    install_global_excepthook()
    base = Path(__file__).resolve().parents[1]
    _ensure_dirs(base)

    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
