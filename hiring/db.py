"""The shared register: one SQLite database that every AI employee and person uses.

The status of a candidate is the hand-off between employees. A change of
status is only saved when the candidate is still in the status the caller
expected, so a person and an employee can never overwrite each other.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (JSON, Boolean, Float, ForeignKey, Integer, String, Text,
                        create_engine, func, select)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_no: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    email_source: Mapped[str] = mapped_column(String(60), default="")
    cv_filename: Mapped[str] = mapped_column(String(255), default="")
    cv_stored: Mapped[str] = mapped_column(String(255), default="")
    cv_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    cv_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), index=True, default="new")
    outcome: Mapped[str] = mapped_column(String(80), default="")
    area: Mapped[str] = mapped_column(String(80), default="")
    area_source: Mapped[str] = mapped_column(String(60), default="")
    area_reasons: Mapped[list] = mapped_column(JSON, default=list)
    area_evidence: Mapped[list] = mapped_column(JSON, default=list)
    suggested_new_area: Mapped[str] = mapped_column(String(80), default="")
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    profile_source: Mapped[str] = mapped_column(String(40), default="")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_parts: Mapped[dict] = mapped_column(JSON, default=dict)
    gaps: Mapped[list] = mapped_column(JSON, default=list)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    questions_source: Mapped[str] = mapped_column(String(40), default="")
    interview_at: Mapped[str] = mapped_column(String(40), default="")
    interview_label: Mapped[str] = mapped_column(String(80), default="")
    result: Mapped[str] = mapped_column(String(10), default="")
    result_comment: Mapped[str] = mapped_column(Text, default="")
    result_at: Mapped[str] = mapped_column(String(40), default="")
    work_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checklist: Mapped[list] = mapped_column(JSON, default=list)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String(40), default="")
    updated_at: Mapped[str] = mapped_column(String(40), default="")


class Draft(Base):
    __tablename__ = "drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="waiting")  # waiting / released / discarded
    written_by: Mapped[str] = mapped_column(String(60), default="")
    check_notes: Mapped[list] = mapped_column(JSON, default=list)
    file: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[str] = mapped_column(String(40), default="")
    released_at: Mapped[str] = mapped_column(String(40), default="")


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    at: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee: Mapped[str] = mapped_column(String(30), index=True)
    routine: Mapped[str] = mapped_column(String(60))
    candidate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[str] = mapped_column(String(40))
    seconds: Mapped[float] = mapped_column(Float, default=0.0)
    outcome: Mapped[str] = mapped_column(String(20))   # ok / fixed / fallback / stopped / error
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")


class Area(Base):
    __tablename__ = "areas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    required_skills: Mapped[list] = mapped_column(JSON, default=list)
    preferred_skills: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    checklist: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_by: Mapped[str] = mapped_column(String(40), default="")


class Brief(Base):
    __tablename__ = "briefs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    created_at: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    written_by: Mapped[str] = mapped_column(String(40), default="")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------------------------
class Paths:
    data: Path = config.DATA_DIR

    @property
    def inbox(self) -> Path: return self.data / "inbox"
    @property
    def outbox(self) -> Path: return self.data / "outbox"
    @property
    def run_logs(self) -> Path: return self.data / "run-logs"
    @property
    def notes(self) -> Path: return self.data / "notes"
    @property
    def db(self) -> Path: return self.data / "register.db"


paths = Paths()
_engine = None
Session = sessionmaker(expire_on_commit=False)
_id_lock = threading.Lock()


def now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def setup(data_dir: Path | None = None) -> None:
    """Create the data folders and database, and copy the starter areas in once."""
    global _engine
    if data_dir is not None:
        paths.data = Path(data_dir)
    for d in (paths.data, paths.inbox, paths.outbox, paths.run_logs, paths.notes):
        d.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(f"sqlite:///{paths.db}", connect_args={"check_same_thread": False, "timeout": 30})
    Session.configure(bind=_engine)
    Base.metadata.create_all(_engine)
    with Session() as s:
        if s.scalar(select(func.count(Area.id))) == 0:
            for a in json.loads(config.AREAS_FILE.read_text(encoding="utf-8")):
                s.add(Area(name=a["name"], description=a.get("description", ""),
                           required_skills=a.get("required_skills", []),
                           preferred_skills=a.get("preferred_skills", []),
                           keywords=a.get("keywords", []), checklist=a.get("checklist", []),
                           active=True, added_by="Starter list"))
        if s.get(Setting, "next_work_id") is None:
            s.add(Setting(key="next_work_id", value=str(config.WORK_ID_START)))
        if s.get(Setting, "next_app_no") is None:
            s.add(Setting(key="next_app_no", value="1"))
        if s.get(Setting, "paused") is None:
            s.add(Setting(key="paused", value="0"))
        s.commit()


# ---- small helpers ----------------------------------------------------------------
def get_setting(key: str, default: str = "") -> str:
    with Session() as s:
        row = s.get(Setting, key)
        return row.value if row else default


def set_setting(key: str, value: str) -> None:
    with Session() as s:
        row = s.get(Setting, key)
        if row:
            row.value = value
        else:
            s.add(Setting(key=key, value=value))
        s.commit()


def log_event(candidate_id: int | None, actor: str, text: str) -> None:
    with Session() as s:
        s.add(Event(candidate_id=candidate_id, at=now(), actor=actor, text=text))
        s.commit()


def log_run(employee: str, routine: str, candidate_id: int | None, started: float, seconds: float,
            outcome: str, model_calls: int, note: str = "") -> None:
    started_at = datetime.fromtimestamp(started).replace(microsecond=0).isoformat()
    with Session() as s:
        s.add(Run(employee=employee, routine=routine, candidate_id=candidate_id, started_at=started_at,
                  seconds=round(seconds, 2), outcome=outcome, model_calls=model_calls, note=note))
        s.commit()
    # The same line also goes to a plain log file, one file per day.
    line = {"at": started_at, "employee": employee, "routine": routine, "candidate_id": candidate_id,
            "seconds": round(seconds, 2), "outcome": outcome, "model_calls": model_calls, "note": note}
    try:
        with open(paths.run_logs / f"{started_at[:10]}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except OSError:
        pass


def next_app_no() -> str:
    with _id_lock, Session() as s:
        row = s.get(Setting, "next_app_no")
        n = int(row.value)
        row.value = str(n + 1)
        s.commit()
    return f"{config.APP_NO_PREFIX}{n:04d}"


def get_candidate(app_no_or_id: str | int) -> Candidate | None:
    with Session() as s:
        if isinstance(app_no_or_id, int):
            return s.get(Candidate, app_no_or_id)
        return s.scalar(select(Candidate).where(Candidate.app_no == app_no_or_id))


def update_candidate(candidate_id: int, expect_status: str | set | None = None, **fields: Any) -> bool:
    """Save fields on a candidate. If expect_status is given, only save when the
    candidate is still in that status. Returns True when saved."""
    with Session() as s:
        c = s.get(Candidate, candidate_id)
        if c is None:
            return False
        if expect_status is not None:
            allowed = {expect_status} if isinstance(expect_status, str) else set(expect_status)
            if c.status not in allowed:
                return False
        for k, v in fields.items():
            setattr(c, k, v)
        c.updated_at = now()
        s.commit()
        return True


def add_flag(candidate_id: int, text: str, by: str) -> None:
    with Session() as s:
        c = s.get(Candidate, candidate_id)
        if c is None:
            return
        if any(f.get("text") == text and f.get("open") for f in (c.flags or [])):
            return
        c.flags = list(c.flags or []) + [{"text": text, "by": by, "at": now(), "open": True}]
        c.updated_at = now()
        s.commit()


def candidates_in(statuses: set[str] | str, limit: int | None = None) -> list[Candidate]:
    statuses = {statuses} if isinstance(statuses, str) else statuses
    with Session() as s:
        q = select(Candidate).where(Candidate.status.in_(statuses)).order_by(Candidate.updated_at, Candidate.id)
        if limit:
            q = q.limit(limit)
        return list(s.scalars(q))


def active_areas() -> list[Area]:
    with Session() as s:
        return list(s.scalars(select(Area).where(Area.active.is_(True)).order_by(Area.id)))


def area_by_name(name: str) -> Area | None:
    with Session() as s:
        for a in s.scalars(select(Area)):
            if a.name.lower() == (name or "").strip().lower():
                return a
    return None


def issue_work_id(candidate_id: int) -> int:
    """Give a passed candidate a 4-digit work ID.

    Rules enforced here, in plain code:
    - only a candidate whose status is "passed" can get an ID;
    - the same email always gets the same ID;
    - IDs start at 1001, count up and are never reused.
    """
    with _id_lock, Session() as s:
        c = s.get(Candidate, candidate_id)
        if c is None:
            raise ValueError("Unknown candidate")
        if c.status != "passed":
            raise PermissionError("A work ID can only be issued after the interviewer enters Pass.")
        if c.work_id:
            return c.work_id
        if c.email:
            same = s.scalar(select(Candidate).where(Candidate.email == c.email, Candidate.work_id.is_not(None),
                                                    Candidate.id != c.id))
            if same is not None:
                c.work_id = same.work_id
                s.commit()
                return c.work_id
        row = s.get(Setting, "next_work_id")
        n = int(row.value)
        if n > config.WORK_ID_MAX:
            raise RuntimeError("No 4-digit work IDs are left.")
        c.work_id = n
        row.value = str(n + 1)
        c.updated_at = now()
        s.commit()
        return n
