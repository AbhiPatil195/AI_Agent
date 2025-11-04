from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any


from models import TaskItem


class TaskPlannerAgent:
    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    # ---------------------------- public API ----------------------------
    def create_from_goal(self, goal: str, append: bool = True) -> List[TaskItem]:
        tasks = self._generate_tasks(goal)
        self._save_tasks(tasks, append=append)
        return tasks

    def list_tasks(self, status: Optional[str] = None, blocked: bool = False, today: bool = False) -> List[TaskItem]:
        tasks = self._load_all()
        if status and status != "all":
            tasks = [t for t in tasks if t.status == status]
        if blocked:
            by_id = {t.id: t for t in tasks}
            done_ids = {t.id for t in tasks if t.status == "done"}
            tasks = [t for t in tasks if t.deps and any((d not in done_ids) for d in t.deps)]
        if today:
            tasks = [t for t in tasks if t.status == "todo" and t.priority == 1]
        tasks.sort(key=lambda t: (t.status != "todo", t.priority, t.id))
        return tasks

    def mark_done(self, task_id: int) -> Optional[TaskItem]:
        tasks = self._load_all()
        found = None
        for t in tasks:
            if t.id == task_id:
                t.status = "done"
                found = t
                break
        if found:
            self._write_store(tasks)
        return found

    # ---------------------------- internals ----------------------------
    def _generate_tasks(self, goal: str) -> List[TaskItem]:
        g = goal.lower()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        def t(title: str, est_min: int, prio: int) -> TaskItem:
            return TaskItem(id=-1, title=title, est_hours=round(est_min / 60.0, 2), priority=prio, status="todo", updated_at=now, goal=goal)

        tasks: List[TaskItem] = []
        if any(k in g for k in ["paper", "report", "manuscript", "article"]):
            tasks = [
                t("Draft outline and abstract", 120, 1),
                t("Collect and format references", 60, 2),
                t("Polish figures and tables", 90, 2),
                t("Write introduction and methods", 180, 1),
                t("Proofread and final formatting", 60, 2),
                t("Submit via portal", 30, 1),
            ]
        elif any(k in g for k in ["presentation", "slides", "deck"]):
            tasks = [
                t("Define audience and key message", 45, 1),
                t("Create slide outline", 60, 1),
                t("Design visuals and charts", 90, 2),
                t("Write speaker notes", 60, 2),
                t("Rehearse and time the talk", 45, 1),
            ]
        elif any(k in g for k in ["feature", "bug", "release", "deploy"]):
            tasks = [
                t("Clarify requirements and acceptance criteria", 45, 1),
                t("Implement changes and unit tests", 120, 1),
                t("Run lint/tests and fix issues", 60, 1),
                t("Prepare changelog and docs", 45, 2),
                t("Tag and release/deploy", 30, 1),
            ]
        else:
            tasks = [
                t("Break down goal into steps", 30, 1),
                t("Identify dependencies and resources", 30, 2),
                t("Schedule work on calendar", 20, 2),
                t("Execute first actionable step", 60, 1),
                t("Review progress and adjust", 20, 2),
            ]

        # Assign sequential IDs continuing from store
        next_id = self._next_id()
        for i, task in enumerate(tasks):
            task.id = next_id + i
        # Simple linear dependency chain to reflect order
        for i in range(1, len(tasks)):
            tasks[i].deps = [tasks[i - 1].id]
        return tasks

    def _next_id(self) -> int:
        tasks = self._load_all()
        return (max((t.id for t in tasks), default=0) + 1)

    def _save_tasks(self, tasks: List[TaskItem], append: bool = True) -> None:
        existing = self._load_all() if append else []
        merged = existing + tasks
        self._write_store(merged)

    def _load_all(self) -> List[TaskItem]:
        if not self.store_path.exists():
            return []
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return []
        items = data.get("tasks", []) if isinstance(data, dict) else []
        tasks: List[TaskItem] = []
        for it in items:
            try:
                # Backward compatibility: accept estimate_min and map to est_hours
                if "estimate_min" in it and "est_hours" not in it:
                    it = dict(it)
                    it["est_hours"] = round(float(it.get("estimate_min", 0)) / 60.0, 2)
                tasks.append(TaskItem(**it))
            except Exception:
                continue
        return tasks

    def _write_store(self, tasks: List[TaskItem]) -> None:
        data: Dict[str, Any] = {"tasks": [t.model_dump() for t in tasks]}
        self.store_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
