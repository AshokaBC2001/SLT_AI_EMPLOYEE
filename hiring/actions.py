"""What the two people can do: the HR officer and the Interviewer.

The web pages call these functions. Every action checks the candidate's current
status first, so an action can only happen at the right moment.
"""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import func, select

from . import checks, config, db, tools


class ActionError(Exception):
    """A message for the person, shown on the page."""


def _candidate(app_no: str) -> db.Candidate:
    c = db.get_candidate(app_no)
    if c is None:
        raise ActionError(f"There is no candidate {app_no}.")
    return c


def _need(c: db.Candidate, statuses: set[str], what: str) -> None:
    if c.status not in statuses:
        raise ActionError(f"{what} is not possible now. {c.app_no} is \"{config.STATUSES[c.status][0]}\".")


def _resolve_flags(c: db.Candidate, starts: tuple[str, ...]) -> list:
    flags = []
    for f in c.flags or []:
        f = dict(f)
        if f.get("open") and f.get("text", "").startswith(starts):
            f["open"] = False
            f["resolved_at"] = db.now()
        flags.append(f)
    return flags


# ---- Adding CVs (HR officer) ----------------------------------------------------------
def add_cv(filename: str, data: bytes, typed_email: str = "") -> dict:
    name = Path(filename or "cv").name[:200]
    ext = Path(name).suffix.lower()
    if ext not in config.ALLOWED_CV_TYPES:
        return {"ok": False, "file": name, "reason": "Only PDF, Word (.docx) and text (.txt) files can be added."}
    if not data:
        return {"ok": False, "file": name, "reason": "The file is empty."}
    if len(data) > config.MAX_UPLOAD_BYTES:
        return {"ok": False, "file": name, "reason": "The file is larger than 5 MB."}
    typed_email = (typed_email or "").strip()
    if typed_email and not checks.EMAIL_RE.fullmatch(typed_email):
        return {"ok": False, "file": name, "reason": f'"{typed_email}" is not a valid email address.'}
    h = tools.file_hash(data)
    with db.Session() as s:
        same = s.scalar(select(db.Candidate).where(db.Candidate.cv_hash == h))
    if same is not None:
        return {"ok": False, "file": name, "reason": f"This CV was already added as {same.app_no}."}
    app_no = db.next_app_no()
    stored = f"{app_no}{ext}"
    path = db.paths.inbox / stored
    path.write_bytes(data)
    try:
        text = tools.read_cv(path)
    except Exception:
        text = ""
    with db.Session() as s:
        c = db.Candidate(app_no=app_no, cv_filename=name, cv_stored=stored, cv_hash=h, cv_text=text,
                         email=typed_email, email_source="Typed by HR officer" if typed_email else "",
                         status="new", created_at=db.now(), updated_at=db.now(),
                         profile={}, area_reasons=[], area_evidence=[], score_parts={}, gaps=[], questions=[],
                         checklist=[], flags=[])
        s.add(c)
        s.commit()
        cid = c.id
    db.log_event(cid, "HR officer", f"Added the CV file {name}.")
    return {"ok": True, "file": name, "app_no": app_no}


def add_samples() -> list[dict]:
    out = []
    for p in sorted(config.SAMPLES_DIR.glob("*.*")):
        if p.suffix.lower() in config.ALLOWED_CV_TYPES and p.is_file():
            out.append(add_cv(p.name, p.read_bytes()))
    return out


def cv_file(app_no: str) -> tuple[Path, str]:
    c = _candidate(app_no)
    path = (db.paths.inbox / c.cv_stored).resolve()
    if db.paths.inbox.resolve() not in path.parents or not path.exists():
        raise ActionError("The CV file is missing.")
    return path, c.cv_filename


# ---- HR officer decisions ----------------------------------------------------------------
def set_email(app_no: str, email: str) -> None:
    c = _candidate(app_no)
    email = (email or "").strip()
    if not checks.EMAIL_RE.fullmatch(email):
        raise ActionError(f'"{email}" is not a valid email address.')
    flags = _resolve_flags(c, ("No email address", "The email typed by the HR officer", "Possible duplicate:"))
    with db.Session() as s:
        other = s.scalar(select(db.Candidate).where(func.lower(db.Candidate.email) == email.lower(),
                                                    db.Candidate.id != c.id))
    if other is not None:
        flags.append({"text": f"Possible duplicate: {other.app_no} has the same email.",
                      "by": "System", "at": db.now(), "open": True})
    db.update_candidate(c.id, email=email, email_source="Typed by HR officer", flags=flags)
    db.log_event(c.id, "HR officer", f"Set the email to {email}.")


def choose_area(app_no: str, area_name: str) -> dict:
    c = _candidate(app_no)
    _need(c, {"needs_area", "borderline", "not_shortlisted_check"}, "Choosing the area")
    area = db.area_by_name(area_name)
    if area is None or not area.active:
        raise ActionError(f'"{area_name}" is not an active area.')
    if not area.required_skills:
        raise ActionError(f"{area.name} has no required skills yet. Add them on the Areas page first.")
    profile = c.profile or tools.rule_profile(c.cv_text, tools.skill_vocabulary(db.active_areas()))
    score, parts, gaps = tools.score_cv(profile, c.cv_text, area)
    status = tools.shortlist_status(score)
    flags = _resolve_flags(c, ("AI suggested a new area", "The Recruiter could not choose", "The scoring rules suggest",
                               "None of the usual", "The area "))
    ok = db.update_candidate(c.id, expect_status=c.status, status=status, area=area.name,
                             area_source="Chosen by HR officer", area_reasons=["Chosen by the HR officer."],
                             area_evidence=[], suggested_new_area="", profile=profile, score=score,
                             score_parts=parts, gaps=gaps, flags=flags)
    if not ok:
        raise ActionError("The candidate changed while you were working. Reload the page.")
    db.log_event(c.id, "HR officer", f"Chose the area {area.name}. Scored {score} of 100 "
                                     f"({config.STATUSES[status][0]}).")
    return {"status": status, "score": score}


def decide(app_no: str, decision: str) -> str:
    c = _candidate(app_no)
    if c.status == "borderline":
        new = {"shortlist": "shortlisted", "not_shortlist": "not_shortlisted"}.get(decision)
        text = {"shortlist": "Shortlisted the borderline candidate.",
                "not_shortlist": "Decided Not shortlisted for the borderline candidate."}.get(decision)
    elif c.status == "not_shortlisted_check":
        new = {"confirm": "not_shortlisted", "not_shortlist": "not_shortlisted", "shortlist": "shortlisted"}.get(decision)
        text = {"confirm": "Confirmed Not shortlisted.", "not_shortlist": "Confirmed Not shortlisted.",
                "shortlist": "Shortlisted the candidate instead (overruled the score)."}.get(decision)
    else:
        raise ActionError(f"No decision is needed now. {c.app_no} is \"{config.STATUSES[c.status][0]}\".")
    if new is None:
        raise ActionError("Unknown decision.")
    if not db.update_candidate(c.id, expect_status=c.status, status=new):
        raise ActionError("The candidate changed while you were working. Reload the page.")
    db.log_event(c.id, "HR officer", text)
    return new


def retry(app_no: str) -> None:
    c = _candidate(app_no)
    _need(c, {"needs_person"}, "Trying again")
    try:
        text = tools.read_cv(db.paths.inbox / c.cv_stored)
    except Exception:
        text = c.cv_text
    flags = _resolve_flags(c, ("Could not read",))
    db.update_candidate(c.id, expect_status="needs_person", status="new", cv_text=text, flags=flags)
    db.log_event(c.id, "HR officer", "Sent the CV back to the Recruiter to try again.")


def close(app_no: str) -> None:
    c = _candidate(app_no)
    _need(c, {"needs_person", "needs_area"}, "Closing")
    db.update_candidate(c.id, expect_status=c.status, status="closed", outcome="Closed by HR officer")
    db.log_event(c.id, "HR officer", "Closed the application without a reply.")


def resolve_flag(app_no: str, index: int) -> None:
    c = _candidate(app_no)
    flags = [dict(f) for f in (c.flags or [])]
    if not 0 <= index < len(flags):
        raise ActionError("Unknown note.")
    flags[index]["open"] = False
    flags[index]["resolved_at"] = db.now()
    db.update_candidate(c.id, flags=flags)
    db.log_event(c.id, "HR officer", f"Marked as checked: {flags[index]['text'][:120]}")


def toggle_checklist(app_no: str, index: int) -> list[dict]:
    c = _candidate(app_no)
    items = [dict(item) for item in (c.checklist or [])]
    if not 0 <= index < len(items):
        raise ActionError("Unknown checklist item.")
    items[index]["done"] = not bool(items[index].get("done"))
    db.update_candidate(c.id, checklist=items)
    state_word = "Completed" if items[index]["done"] else "Reopened"
    db.log_event(c.id, "HR officer", f"{state_word} checklist item: {items[index].get('item', '')[:120]}")
    return items


def free_interview_slots(count: int = 21) -> list[dict[str, str]]:
    with db.Session() as s:
        taken = {x for x in s.scalars(select(db.Candidate.interview_at).where(db.Candidate.interview_at != ""))}
    return tools.upcoming_interview_slots(taken, count=count)


def reschedule_interview(app_no: str, slot_iso: str) -> dict:
    c = _candidate(app_no)
    _need(c, {"invite_ready", "awaiting_result", "on_hold"}, "Changing the interview slot")
    slot_iso = (slot_iso or "").strip()
    try:
        label = tools.format_slot_label(slot_iso)
    except ValueError as e:
        raise ActionError("Invalid interview date and time.") from e
    with db.Session() as s:
        clash = s.scalar(select(db.Candidate).where(db.Candidate.interview_at == slot_iso,
                                                    db.Candidate.id != c.id))
        if clash is not None:
            raise ActionError(f"That slot is already booked for {clash.app_no}.")
        cand = s.get(db.Candidate, c.id)
        old_label = cand.interview_label
        cand.interview_at = slot_iso
        cand.interview_label = label
        cand.updated_at = db.now()
        drafts = list(s.scalars(select(db.Draft).where(
            db.Draft.candidate_id == c.id, db.Draft.kind == "invitation", db.Draft.status == "waiting")))
        for d in drafts:
            if old_label and old_label in d.body:
                d.body = d.body.replace(old_label, label)
            facts, _, _ = _draft_facts(cand)
            _, problems = checks.check_draft({"subject": d.subject, "body": d.body}, facts,
                                             [m for m in (cand.area, label) if m])
            d.check_notes = problems
        s.commit()
    db.log_event(c.id, "HR officer", f"Changed the interview slot to {label}.")
    return {"interview_at": slot_iso, "interview_label": label}


# ---- Interviewer -------------------------------------------------------------------------
def enter_result(app_no: str, result: str, comment: str = "") -> str:
    c = _candidate(app_no)
    result = (result or "").capitalize()
    if c.status == "awaiting_result":
        allowed = {"Pass", "Fail", "Hold"}
    elif c.status == "on_hold":
        allowed = {"Pass", "Fail"}
    else:
        raise ActionError(f"A result cannot be entered now. {c.app_no} is \"{config.STATUSES[c.status][0]}\".")
    if result not in allowed:
        raise ActionError("Choose " + ", ".join(sorted(allowed)) + ".")
    comment = (comment or "").strip()[:2000]
    new = {"Pass": "passed", "Fail": "failed", "Hold": "hold"}[result]
    if not db.update_candidate(c.id, expect_status=c.status, status=new, result=result, result_comment=comment,
                               result_at=db.now()):
        raise ActionError("The candidate changed while you were working. Reload the page.")
    db.log_event(c.id, "Interviewer", f"Entered the result: {result}." + (f" Comment: {comment}" if comment else ""))
    return new


# ---- Replies (HR officer releases every email) -----------------------------------------
KIND_LABELS = {"invitation": "interview invitation", "not_shortlisted": "Not shortlisted reply",
               "rejection": "rejection reply", "hold": "hold note", "acceptance": "acceptance email"}
RELEASE_MOVES = {
    "invitation": ("invite_ready", "awaiting_result", ""),
    "not_shortlisted": ("reply_ready", "closed", "Not shortlisted"),
    "rejection": ("reply_ready", "closed", "Not selected after interview"),
    "hold": ("hold_note_ready", "on_hold", ""),
    "acceptance": ("offer_ready", "closed", "Selected"),
}


def _draft_facts(c: db.Candidate) -> tuple[dict, list[str], list[str]]:
    facts = {"name": c.name or "Student", "area": c.area or "the internship", "app_no": c.app_no,
             "interview": c.interview_label or None, "work_id": str(c.work_id) if c.work_id else None}
    facts = {k: v for k, v in facts.items() if v}
    return facts, [], []


def edit_draft(draft_id: int, subject: str, body: str) -> list[str]:
    with db.Session() as s:
        d = s.get(db.Draft, draft_id)
        if d is None or d.status != "waiting":
            raise ActionError("This email can no longer be edited.")
        c = s.get(db.Candidate, d.candidate_id)
        facts, _, _ = _draft_facts(c)
        must = {"invitation": [c.area, c.interview_label], "acceptance": [c.area, str(c.work_id or "")]}.get(d.kind, [])
        _, problems = checks.check_draft({"subject": subject, "body": body}, facts, [m for m in must if m])
        d.subject, d.body = subject.strip()[:200], body.strip()
        d.written_by = "Edited by HR officer"
        d.check_notes = problems
        s.commit()
        cid = c.id
    db.log_event(cid, "HR officer", "Edited the draft email.")
    return problems


def release_draft(draft_id: int) -> str:
    with db.Session() as s:
        d = s.get(db.Draft, draft_id)
        if d is None or d.status != "waiting":
            raise ActionError("This email is not waiting for release.")
        c = s.get(db.Candidate, d.candidate_id)
        if not c.email or not checks.EMAIL_RE.fullmatch(c.email):
            raise ActionError("Add the student's email address on the candidate page before releasing.")
        before, after, outcome = RELEASE_MOVES[d.kind]
        if c.status != before:
            raise ActionError(f"{c.app_no} is \"{config.STATUSES[c.status][0]}\", so this email cannot be released now.")
        fname = re.sub(r"[^A-Za-z0-9_-]", "", f"{c.app_no}_{d.kind}_{d.id}") + ".txt"
        (db.paths.outbox / fname).write_text(
            f"To: {c.name} <{c.email}>\nSubject: {d.subject}\nReleased: {db.now()}\n\n{d.body}\n", encoding="utf-8")
        d.status, d.released_at, d.file = "released", db.now(), fname
        c.status = after
        if outcome:
            c.outcome = outcome + (f" (work ID {c.work_id})" if d.kind == "acceptance" and c.work_id else "")
        c.updated_at = db.now()
        s.commit()
        cid, label = c.id, KIND_LABELS[d.kind]
    db.log_event(cid, "HR officer", f"Released the {label}. It was saved to the outbox (not sent).")
    return after


def release_all_ready() -> dict:
    with db.Session() as s:
        rows = list(s.execute(select(db.Draft, db.Candidate)
                              .join(db.Candidate, db.Candidate.id == db.Draft.candidate_id)
                              .where(db.Draft.status == "waiting")
                              .order_by(db.Draft.id)).all())
    released = 0
    skipped = 0
    for d, c in rows:
        before = RELEASE_MOVES.get(d.kind, ("", "", ""))[0]
        if c.status == before and c.email and checks.EMAIL_RE.fullmatch(c.email):
            try:
                release_draft(d.id)
                released += 1
            except ActionError:
                skipped += 1
        else:
            skipped += 1
    return {"released": released, "skipped": skipped}


# ---- Areas (HR officer) --------------------------------------------------------------------
def _list(value, sep: str = r"[,\n]") -> list[str]:
    if isinstance(value, str):
        value = re.split(sep, value)
    out = []
    for v in value or []:
        v = str(v).strip()[:120]
        if v and v not in out:
            out.append(v)
    return out[:30]


def save_area(area_id: int | None, name: str, description: str, required, preferred, keywords, checklist,
              active: bool = True) -> int:
    name = checks.clean_area_name(name)
    if not name:
        raise ActionError("Give the area a name.")
    if name.lower() == config.NEEDS_REVIEW_AREA.lower():
        raise ActionError("That name is reserved.")
    required = _list(required)
    if not required:
        raise ActionError("Add at least one required skill, so CVs can be scored for this area.")
    with db.Session() as s:
        clash = s.scalar(select(db.Area).where(func.lower(db.Area.name) == name.lower()))
        if clash is not None and clash.id != area_id:
            raise ActionError(f"An area called {name} already exists.")
        old_name = ""
        if area_id is None:
            a = db.Area(name=name, added_by="HR officer")
            s.add(a)
        else:
            a = s.get(db.Area, area_id)
            if a is None:
                raise ActionError("Unknown area.")
            old_name = a.name
        a.name, a.description = name, (description or "").strip()[:300]
        a.required_skills, a.preferred_skills = required, _list(preferred)
        a.keywords, a.checklist = _list(keywords), _list(checklist, r"\n")
        a.active = bool(active)
        if old_name and old_name != name:
            for c in s.scalars(select(db.Candidate).where(db.Candidate.area == old_name)):
                c.area = name
        s.commit()
        new_id = a.id
    db.log_event(None, "HR officer", f"{'Added' if area_id is None else 'Updated'} the area {name}.")
    return new_id


def ask_cv(app_no: str, question: str) -> dict:
    from . import flows
    c = _candidate(app_no)
    q = (question or "").strip()[:240]
    if len(q) < 3:
        raise ActionError("Write a short question about this CV first.")
    if not c.cv_text or len(c.cv_text.strip()) < 20:
        raise ActionError("There is no readable CV text for this candidate.")
    profile = c.profile or tools.rule_profile(c.cv_text, tools.skill_vocabulary(db.active_areas()))
    return flows.ask_candidate_cv(c.id, c.cv_text, profile, q)

