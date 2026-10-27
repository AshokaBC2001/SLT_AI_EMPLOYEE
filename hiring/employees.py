"""Loads the AI employees from their Markdown folders and runs checked model steps.

Each employee is a folder in employees/:
    ROLE.md       who the employee is (goes into every prompt)
    SCHEDULE.md   when it runs ("Runs every: 30 seconds" or "Runs daily at: 08:00")
    RELEASES.md   what it may do without a person
    routines/<name>/SKILL.md   one routine; the "Instructions for the model" and "Output"
                               sections go into the prompt

Editing these files changes how the employee works, without touching the code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import config, db, llm
from .checks import parse_json_object

EMPLOYEES = {
    "recruiter": "Recruiter",
    "coordinator": "Coordinator",
    "onboarding": "Onboarding",
    "chief-of-staff": "Chief of staff",
}


def folder(key: str) -> Path:
    return config.EMPLOYEES_DIR / key


def read(key: str, rel: str) -> str:
    p = folder(key) / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def section(text: str, heading: str) -> str:
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)", text, flags=re.M | re.S | re.I)
    return m.group(1).strip() if m else ""


def role_text(key: str) -> str:
    return read(key, "ROLE.md").strip()


def role_summary(key: str) -> str:
    m = re.search(r"^In short:\s*(.+)$", role_text(key), flags=re.M)
    if m:
        return m.group(1).strip()
    text = re.sub(r"^#.*$", "", role_text(key), flags=re.M).strip()
    return text.split("\n\n")[0].replace("\n", " ")


def routines(key: str) -> list[dict]:
    out = []
    base = folder(key) / "routines"
    if not base.exists():
        return out
    order = {
        "recruiter": ["parse-cv", "duplicate-check", "choose-area", "score-match", "skill-gap", "shortlist", "ask-cv"],
        "coordinator": ["invite-and-slots", "prepare-questions", "reply-not-shortlisted", "update-register",
                        "reply-failed-or-hold"],
        "onboarding": ["issue-work-id", "draft-acceptance", "induction-checklist"],
        "chief-of-staff": ["read-run-logs", "flag-stalled", "morning-brief"],
    }.get(key, [])
    names = sorted([p.name for p in base.iterdir() if (p / "SKILL.md").exists()],
                   key=lambda n: order.index(n) if n in order else 99)
    for name in names:
        text = (base / name / "SKILL.md").read_text(encoding="utf-8")
        starts = re.search(r"^Starts when:\s*(.+)$", text, flags=re.M)
        done = re.search(r"^Done by:\s*(.+)$", text, flags=re.M)
        out.append({"name": name, "starts_when": starts.group(1).strip() if starts else "",
                    "done_by": done.group(1).strip() if done else "",
                    "what": section(text, "What it does"),
                    "uses_model": bool(section(text, "Instructions for the model"))})
    return out


def instructions(key: str, routine: str) -> str:
    text = read(key, f"routines/{routine}/SKILL.md")
    instr = section(text, "Instructions for the model")
    out = section(text, "Output")
    return f"{instr}\n\n{out}".strip()


def schedule(key: str) -> dict:
    text = read(key, "SCHEDULE.md")
    every = re.search(r"Runs every:\s*(\d+)\s*(second|minute|hour)", text, flags=re.I)
    daily = re.search(r"Runs daily at:\s*(\d{1,2}):(\d{2})", text, flags=re.I)
    seconds = None
    if every:
        n, unit = int(every.group(1)), every.group(2).lower()
        seconds = n * {"second": 1, "minute": 60, "hour": 3600}[unit]
    summary = re.sub(r"^#.*$", "", text, flags=re.M).strip()
    return {"every_seconds": seconds,
            "daily_at": f"{int(daily.group(1)):02d}:{daily.group(2)}" if daily else None,
            "text": summary}


# ---- Lessons: each employee remembers what went wrong, without personal data ----------
LESSON_RULES = [
    ("not written in the CV", "Only copy words that are written in the CV."),
    ("numbers that are not in the facts", "Do not add dates, times or numbers that are not in the facts."),
    ("placeholder", "Never write placeholders like [Name]. Use the real facts."),
    ("evidence phrases", "Evidence must be short phrases copied exactly from the CV."),
    ("not JSON", "Reply with one JSON object only, with no other text."),
    ("not a JSON object", "Reply with one JSON object only, with no other text."),
    ("question mark", "Every question must be a full sentence ending with a question mark."),
    ("greet the student", "Always greet the student by first name."),
    ("exactly as given", "Copy the area, date and IDs exactly as written in the facts."),
    ("too long", "Keep the text short."),
    ("too short", "Write at least three full sentences."),
]


def _notes_file(key: str) -> Path:
    return db.paths.notes / f"{key}.md"


def lessons(key: str) -> list[str]:
    p = _notes_file(key)
    if not p.exists():
        return []
    return [line[2:].strip() for line in p.read_text(encoding="utf-8").splitlines() if line.startswith("- ")]


def add_lessons(key: str, problems: list[str]) -> None:
    current = lessons(key)
    changed = False
    for problem in problems:
        for needle, lesson in LESSON_RULES:
            if needle.lower() in problem.lower() and lesson not in current:
                current.append(lesson)
                changed = True
    if changed:
        current = current[-8:]
        _notes_file(key).write_text(f"# Lessons for the {EMPLOYEES.get(key, key)}\n\n" +
                                    "\n".join(f"- {x}" for x in current) + "\n", encoding="utf-8")


# ---- One model step with checks, fixes and a fallback --------------------------------
@dataclass
class StepResult:
    value: Any
    how: str                    # ok / fixed / fallback
    calls: int
    problems: list[str] = field(default_factory=list)


def ask_checked(key: str, routine: str, task_text: str,
                check: Callable[[dict], tuple[Any, list[str]]],
                fallback: Callable[[], Any], max_tokens: int | None = None) -> StepResult:
    """Ask the model, check the answer in plain code, send problems back for a fix,
    and use the fallback after the allowed fixes. llm.ModelUnavailable is not caught."""
    learned = lessons(key)
    system = role_text(key) + f"\n\nROUTINE: {routine}\n\n" + instructions(key, routine)
    if learned:
        system += "\n\nLessons from earlier runs:\n" + "\n".join(f"- {x}" for x in learned)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": task_text}]
    calls = 0
    problems: list[str] = []
    for attempt in range(1 + config.MAX_FIXES):
        text = llm.chat(messages, json_mode=True, max_tokens=max_tokens)
        calls += 1
        try:
            data = parse_json_object(text)
            value, problems = check(data)
        except ValueError as e:
            value, problems = None, [str(e)]
        if not problems:
            return StepResult(value, "ok" if attempt == 0 else "fixed", calls)
        add_lessons(key, problems)
        messages = messages + [
            {"role": "assistant", "content": text[:3000]},
            {"role": "user", "content": "Your answer did not pass these checks:\n" +
             "\n".join(f"- {p}" for p in problems) +
             "\nFix them and reply with the corrected JSON object only."},
        ]
    return StepResult(fallback(), "fallback", calls, problems)
