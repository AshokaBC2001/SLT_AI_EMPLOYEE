"""How each AI employee works, written as LangGraph graphs.

The status in the register is the hand-off between employees:
    Recruiter    New CV                                -> Shortlisted / Borderline / Not shortlisted (confirm) / Area needs a person
    Coordinator  Shortlisted                           -> Invitation waiting for release
                 Not shortlisted                       -> Reply waiting for release
                 Failed / On hold (result entered)     -> Reply / Hold note waiting for release
    Onboarding   Passed                                -> Acceptance waiting for release
    Chief of staff (daily)                             -> morning brief, stalled flags

Each graph reads one candidate, does its routines and saves everything in one
last step, only if the candidate is still in the status it started from.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select

from . import checks, config, db, llm, tools
from .employees import EMPLOYEES, StepResult, ask_checked

# ---- What each employee is doing (shown on the AI team page) ------------------------
TEAM: dict[str, dict] = {k: {"state": "idle", "doing": "", "last_run": "", "last_note": ""} for k in EMPLOYEES}
NOTICE = {"text": "", "at": ""}      # e.g. "The model server is not running"
WORK_LOCK = threading.Lock()         # one model job at a time (8GB Mac, one local model)

TRIGGERS = {
    "recruiter": {"new"},
    "coordinator": {"shortlisted", "not_shortlisted", "failed", "hold"},
    "onboarding": {"passed"},
}


def _doing(key: str, text: str) -> None:
    TEAM[key].update(state="working" if text else "idle", doing=text)


def _cv_block(text: str) -> str:
    return "CV TEXT:\n<<<\n" + text[:config.MAX_CV_CHARS] + "\n>>>"


def _json(label: str, obj: Any) -> str:
    return f"{label} (JSON):\n" + json.dumps(obj, ensure_ascii=False, indent=1)


def _record(key: str, routine: str, cid: int | None, started: float, result: StepResult | None = None,
            outcome: str = "ok", note: str = "") -> None:
    if result is not None:
        outcome = result.how
        if result.problems and not note:
            note = "Last problems: " + "; ".join(result.problems[:3])
    db.log_run(EMPLOYEES[key], routine, cid, started, time.time() - started, outcome,
               result.calls if result else 0, note)


HOW_TEXT = {"ok": "passed the checks", "fixed": "passed the checks after a fix",
            "fallback": "the model's answers failed the checks, so rules were used"}


# =====================================================================================
# Recruiter
# =====================================================================================
class RecruiterState(TypedDict, total=False):
    cid: int
    cv_text: str
    typed_email: str
    profile: dict
    profile_source: str
    name: str
    email: str
    email_source: str
    area: str
    area_source: str
    reasons: list
    evidence: list
    new_area: str
    score: int | None
    parts: dict
    gaps: list
    status: str
    flags: list
    events: list


def r_load(s: RecruiterState) -> RecruiterState:
    c = db.get_candidate(s["cid"])
    return {"cv_text": c.cv_text or "", "typed_email": c.email if c.email_source == "Typed by HR officer" else "",
            "flags": [], "events": []}


def r_route_text(s: RecruiterState) -> str:
    return "parse" if len((s.get("cv_text") or "").strip()) >= 80 else "unreadable"


def r_unreadable(s: RecruiterState) -> RecruiterState:
    return {"status": "needs_person",
            "flags": s["flags"] + ["Could not read enough text from this file. It may be a scanned PDF. "
                                   "Upload the CV as a Word or text file instead."],
            "events": s["events"] + ["Could not read the CV text."]}


def r_parse_cv(s: RecruiterState) -> RecruiterState:
    started = time.time()
    _doing("recruiter", "Reading a CV")
    cv_text = s["cv_text"]
    vocab = tools.skill_vocabulary(db.active_areas())
    removed_holder: list = []

    def check(data):
        clean, problems, removed = checks.check_profile(data, cv_text)
        removed_holder[:] = removed
        return clean, problems

    res = ask_checked("recruiter", "parse-cv", _cv_block(cv_text), check,
                      lambda: tools.rule_profile(cv_text, vocab))
    profile = dict(res.value or {})
    rules = tools.rule_profile(cv_text, vocab)
    for k in ("email", "phone", "name"):          # fill gaps the model left empty
        if not profile.get(k) and rules.get(k):
            profile[k] = rules[k]
    flags = list(s["flags"])
    note = f"{len(removed_holder)} item(s) removed that were not in the CV" if removed_holder and res.how != "fallback" else ""
    if res.how == "fallback":
        flags.append("The profile was made by simple rules because the model's answers failed the checks. "
                     "Read the CV to confirm it.")
    _record("recruiter", "parse-cv", s["cid"], started, res, note=note)
    return {"profile": profile, "profile_source": "Rules" if res.how == "fallback" else "AI",
            "flags": flags,
            "events": s["events"] + [f"Read the CV and wrote the profile ({HOW_TEXT[res.how]})."
                                     + (f" {note}." if note else "")]}


def r_duplicate_check(s: RecruiterState) -> RecruiterState:
    started = time.time()
    p = s["profile"]
    flags = list(s["flags"])
    cv_email = (p.get("email") or "").strip()
    typed = (s.get("typed_email") or "").strip()
    if typed:
        email, source = typed, "Typed by HR officer"
        if cv_email and cv_email.lower() != typed.lower():
            flags.append(f"The email typed by the HR officer ({typed}) is different from the CV ({cv_email}).")
    elif cv_email:
        email, source = cv_email, "Read from CV"
    else:
        email, source = "", ""
        flags.append("No email address was found. Add one on this page before any reply can be released.")
    if email:
        with db.Session() as ses:
            other = ses.scalar(select(db.Candidate).where(func.lower(db.Candidate.email) == email.lower(),
                                                          db.Candidate.id != s["cid"]))
            if other is not None:
                flags.append(f"Possible duplicate: {other.app_no} has the same email.")
    _record("recruiter", "duplicate-check", s["cid"], started)
    return {"name": (p.get("name") or "").strip(), "email": email, "email_source": source, "flags": flags}


def r_choose_area(s: RecruiterState) -> RecruiterState:
    started = time.time()
    _doing("recruiter", "Choosing an area")
    areas = db.active_areas()
    names = [a.name for a in areas]
    cv_text = s["cv_text"]
    area_list = [{"name": a.name, "description": a.description, "required_skills": a.required_skills} for a in areas]
    task = (_json("AREAS", area_list) + "\n\n" + _json("PROFILE", s["profile"]) + "\n\n" + _cv_block(cv_text))
    best_name, best_score, best_share = tools.best_area_by_rules(s["profile"], cv_text, areas)

    def fallback():
        if best_name and best_share >= 0.5:
            return {"area": best_name, "new_area": "", "reasons": [f"Most required skills of {best_name} are in the CV."],
                    "evidence": [], "by_rules": True}
        return {"area": config.NEEDS_REVIEW_AREA, "new_area": "", "reasons": [], "evidence": []}

    res = ask_checked("recruiter", "choose-area", task,
                      lambda d: checks.check_area(d, names, cv_text), fallback)
    v = res.value
    flags = list(s["flags"])
    events = list(s["events"])
    area, source = v["area"], ("Chosen by rules" if v.get("by_rules") else "Suggested by AI")
    if v.get("new_area"):
        flags.append(f'AI suggested a new area: "{v["new_area"]}". Add it on the Areas page, or choose an area.')
        events.append(f'Suggested a new area: {v["new_area"]}.')
        area = ""
    elif area == config.NEEDS_REVIEW_AREA:
        flags.append("The Recruiter could not choose an area. Please choose one.")
        events.append("Could not choose an area; asked the HR officer.")
        area = ""
    else:
        events.append(f"Chose the area {area} ({'chosen by rules' if v.get('by_rules') else 'suggested by AI'}; {HOW_TEXT[res.how]}).")
        # Second opinion from the scoring rules
        chosen = next(a for a in areas if a.name == area)
        cv = checks.CVText(cv_text)
        req = chosen.required_skills or []
        share = (sum(1 for x in req if cv.has(x)) / len(req)) if req else 0
        if req and share == 0:
            flags.append(f"None of the usual {area} skills are in this CV. Check the area.")
        elif best_name and best_name != area and best_share >= 0.5 and share < 0.34:
            flags.append(f"The scoring rules suggest {best_name} instead of {area}. Check the area.")
    _record("recruiter", "choose-area", s["cid"], started, res)
    return {"area": area, "area_source": source if area else "", "reasons": v.get("reasons", []),
            "evidence": v.get("evidence", []), "new_area": v.get("new_area", ""), "flags": flags, "events": events}


def r_route_area(s: RecruiterState) -> str:
    return "score" if s.get("area") else "needs_area"


def r_needs_area(s: RecruiterState) -> RecruiterState:
    return {"status": "needs_area"}


def r_score_match(s: RecruiterState) -> RecruiterState:
    started = time.time()
    area = db.area_by_name(s["area"])
    score, parts, gaps = tools.score_cv(s["profile"], s["cv_text"], area)
    _record("recruiter", "score-match", s["cid"], started)
    if score is None:
        return {"score": None, "parts": {}, "gaps": [], "status": "needs_area",
                "flags": s["flags"] + [f"The area {s['area']} has no required skills yet, so it cannot be scored. "
                                       "Add them on the Areas page."]}
    return {"score": score, "parts": parts, "gaps": gaps,
            "events": s["events"] + [f"Scored {score} of 100 for {s['area']}."]}


def r_skill_gap(s: RecruiterState) -> RecruiterState:
    started = time.time()
    _record("recruiter", "skill-gap", s["cid"], started)
    gaps = s.get("gaps") or []
    return {"events": s["events"] + [("Skill gaps: " + ", ".join(gaps) + ".") if gaps else "No skill gaps."]}


def r_shortlist(s: RecruiterState) -> RecruiterState:
    started = time.time()
    status = tools.shortlist_status(s["score"])
    _record("recruiter", "shortlist", s["cid"], started)
    text = {"shortlisted": "Shortlisted (score 60 or above).",
            "borderline": "Borderline score (50 to 59); the HR officer decides.",
            "not_shortlisted_check": "Score below 50; the HR officer must confirm Not shortlisted."}[status]
    return {"status": status, "events": s["events"] + [text]}


def r_save(s: RecruiterState) -> RecruiterState:
    fields: dict[str, Any] = {"status": s["status"]}
    if "profile" in s:
        fields.update(profile=s["profile"], profile_source=s.get("profile_source", ""),
                      name=s.get("name", ""), email=s.get("email", ""), email_source=s.get("email_source", ""),
                      area=s.get("area", ""), area_source=s.get("area_source", ""),
                      area_reasons=s.get("reasons", []), area_evidence=s.get("evidence", []),
                      suggested_new_area=s.get("new_area", ""), score=s.get("score"),
                      score_parts=s.get("parts", {}), gaps=s.get("gaps", []))
    if db.update_candidate(s["cid"], expect_status="new", **fields):
        for e in s.get("events", []):
            db.log_event(s["cid"], "Recruiter", e)
        for f in s.get("flags", []):
            db.add_flag(s["cid"], f, "Recruiter")
    return {}


def _build_recruiter():
    g = StateGraph(RecruiterState)
    for name, fn in [("load", r_load), ("unreadable", r_unreadable), ("parse_cv", r_parse_cv),
                     ("duplicate_check", r_duplicate_check), ("choose_area", r_choose_area),
                     ("needs_area", r_needs_area), ("score_match", r_score_match), ("skill_gap", r_skill_gap),
                     ("shortlist", r_shortlist), ("save", r_save)]:
        g.add_node(name, fn)
    g.add_edge(START, "load")
    g.add_conditional_edges("load", r_route_text, {"parse": "parse_cv", "unreadable": "unreadable"})
    g.add_edge("unreadable", "save")
    g.add_edge("parse_cv", "duplicate_check")
    g.add_edge("duplicate_check", "choose_area")
    g.add_conditional_edges("choose_area", r_route_area, {"score": "score_match", "needs_area": "needs_area"})
    g.add_edge("needs_area", "save")
    g.add_conditional_edges("score_match", lambda s: "gap" if s.get("score") is not None else "save",
                            {"gap": "skill_gap", "save": "save"})
    g.add_edge("skill_gap", "shortlist")
    g.add_edge("shortlist", "save")
    g.add_edge("save", END)
    return g.compile()


# =====================================================================================
# Coordinator
# =====================================================================================
class CoordinatorState(TypedDict, total=False):
    cid: int
    start_status: str
    c: dict
    slot_iso: str
    slot_label: str
    questions: list
    questions_source: str
    drafts: list
    status: str
    flags: list
    events: list


def _snapshot(cid: int) -> dict:
    c = db.get_candidate(cid)
    return {"name": c.name, "email": c.email, "area": c.area, "app_no": c.app_no, "profile": c.profile or {},
            "gaps": c.gaps or [], "result": c.result, "work_id": c.work_id, "status": c.status,
            "interview_label": c.interview_label}


def _facts(c: dict, **extra) -> dict:
    facts = {"name": c["name"] or "Student", "first_name": (c["name"] or "Student").split()[0],
             "area": c["area"] or "the internship", "app_no": c["app_no"]}
    facts.update({k: v for k, v in extra.items() if v is not None})
    return facts


def _draft(key: str, routine: str, kind: str, cid: int, facts: dict, must_include: list[str],
           must_not: list[str] | None = None) -> dict:
    started = time.time()
    res = ask_checked(key, routine, _json("FACTS", facts),
                      lambda d: checks.check_draft(d, facts, must_include, must_not),
                      lambda: tools.template_draft(kind, facts))
    _record(key, routine, cid, started, res)
    written_by = {"ok": "AI", "fixed": "AI (fixed after a check)", "fallback": "Template (AI draft failed the checks)"}[res.how]
    notes = [] if res.how != "fallback" else res.problems[:3]
    return {"kind": kind, "subject": res.value["subject"], "body": res.value["body"],
            "written_by": written_by, "check_notes": notes}


def c_load(s: CoordinatorState) -> CoordinatorState:
    c = _snapshot(s["cid"])
    return {"c": c, "start_status": c["status"], "drafts": [], "flags": [], "events": []}


def c_route(s: CoordinatorState) -> str:
    return {"shortlisted": "pick_slot", "not_shortlisted": "draft_not_shortlisted",
            "failed": "update_register", "hold": "update_register"}[s["start_status"]]


def c_pick_slot(s: CoordinatorState) -> CoordinatorState:
    started = time.time()
    _doing("coordinator", "Booking an interview slot")
    with db.Session() as ses:
        taken = {x for x in ses.scalars(select(db.Candidate.interview_at).where(db.Candidate.interview_at != ""))}
    iso, label = tools.pick_interview_slot(taken)
    _record("coordinator", "invite-and-slots", s["cid"], started, note=f"Slot {label}")
    return {"slot_iso": iso, "slot_label": label, "events": s["events"] + [f"Booked the interview slot {label}."]}


def c_prepare_questions(s: CoordinatorState) -> CoordinatorState:
    started = time.time()
    _doing("coordinator", "Preparing interview questions")
    c = s["c"]
    task = _json("FACTS", {"area": c["area"], "skill_gaps": c["gaps"],
                           "projects": (c["profile"].get("projects") or [])[:5],
                           "skills": (c["profile"].get("skills") or [])[:15]})
    res = ask_checked("coordinator", "prepare-questions", task, checks.check_questions,
                      lambda: tools.template_questions(c["area"], c["gaps"], c["profile"]))
    _record("coordinator", "prepare-questions", s["cid"], started, res)
    return {"questions": res.value, "questions_source": "Standard questions" if res.how == "fallback" else "AI",
            "events": s["events"] + [f"Prepared {len(res.value)} interview questions ({HOW_TEXT[res.how]})."]}


def c_draft_invitation(s: CoordinatorState) -> CoordinatorState:
    _doing("coordinator", "Writing an interview invitation")
    c = s["c"]
    facts = _facts(c, interview=s["slot_label"])
    d = _draft("coordinator", "invite-and-slots", "invitation", s["cid"], facts, [c["area"], s["slot_label"]])
    return {"drafts": [d], "status": "invite_ready",
            "events": s["events"] + [f"Drafted the interview invitation ({d['written_by']})."]}


def c_draft_not_shortlisted(s: CoordinatorState) -> CoordinatorState:
    _doing("coordinator", "Writing a reply")
    facts = _facts(s["c"])
    d = _draft("coordinator", "reply-not-shortlisted", "not_shortlisted", s["cid"], facts, [], ["congratulation"])
    return {"drafts": [d], "status": "reply_ready",
            "events": s["events"] + [f"Drafted the Not shortlisted reply ({d['written_by']})."]}


def c_update_register(s: CoordinatorState) -> CoordinatorState:
    started = time.time()
    word = {"failed": "Fail", "hold": "Hold"}[s["start_status"]]
    _record("coordinator", "update-register", s["cid"], started, note=f"Result {word}")
    return {"events": s["events"] + [f"Recorded the interviewer's result: {word}."]}


def c_route_result(s: CoordinatorState) -> str:
    return "draft_rejection" if s["start_status"] == "failed" else "draft_hold"


def c_draft_rejection(s: CoordinatorState) -> CoordinatorState:
    _doing("coordinator", "Writing a reply")
    facts = _facts(s["c"], message_type="rejection")
    d = _draft("coordinator", "reply-failed-or-hold", "rejection", s["cid"], facts, [], ["congratulation"])
    return {"drafts": [d], "status": "reply_ready",
            "events": s["events"] + [f"Drafted the rejection reply ({d['written_by']})."]}


def c_draft_hold(s: CoordinatorState) -> CoordinatorState:
    _doing("coordinator", "Writing a hold note")
    facts = _facts(s["c"], message_type="hold")
    d = _draft("coordinator", "reply-failed-or-hold", "hold", s["cid"], facts, [], ["congratulation"])
    return {"drafts": [d], "status": "hold_note_ready",
            "events": s["events"] + [f"Drafted the hold note ({d['written_by']})."]}


def _save_with_drafts(key: str, s: dict, fields: dict) -> bool:
    actor = EMPLOYEES[key]
    with db.Session() as ses:
        c = ses.get(db.Candidate, s["cid"])
        if c is None or c.status != s["start_status"]:
            return False
        for k, v in fields.items():
            setattr(c, k, v)
        c.updated_at = db.now()
        for d in s.get("drafts", []):
            for old in ses.scalars(select(db.Draft).where(
                    db.Draft.candidate_id == c.id, db.Draft.kind == d["kind"], db.Draft.status == "waiting")):
                old.status = "discarded"
            ses.add(db.Draft(candidate_id=c.id, kind=d["kind"], subject=d["subject"], body=d["body"],
                             status="waiting", written_by=d["written_by"], check_notes=d["check_notes"],
                             created_at=db.now()))
        ses.commit()
    for e in s.get("events", []):
        db.log_event(s["cid"], actor, e)
    for f in s.get("flags", []):
        db.add_flag(s["cid"], f, actor)
    return True


def c_save(s: CoordinatorState) -> CoordinatorState:
    fields: dict[str, Any] = {"status": s["status"]}
    if s.get("slot_iso"):
        fields.update(interview_at=s["slot_iso"], interview_label=s["slot_label"],
                      questions=s.get("questions", []), questions_source=s.get("questions_source", ""))
    _save_with_drafts("coordinator", s, fields)
    return {}


def _build_coordinator():
    g = StateGraph(CoordinatorState)
    for name, fn in [("load", c_load), ("pick_slot", c_pick_slot), ("prepare_questions", c_prepare_questions),
                     ("draft_invitation", c_draft_invitation), ("draft_not_shortlisted", c_draft_not_shortlisted),
                     ("update_register", c_update_register), ("draft_rejection", c_draft_rejection),
                     ("draft_hold", c_draft_hold), ("save", c_save)]:
        g.add_node(name, fn)
    g.add_edge(START, "load")
    g.add_conditional_edges("load", c_route, {"pick_slot": "pick_slot", "draft_not_shortlisted": "draft_not_shortlisted",
                                              "update_register": "update_register"})
    g.add_edge("pick_slot", "prepare_questions")
    g.add_edge("prepare_questions", "draft_invitation")
    g.add_edge("draft_invitation", "save")
    g.add_edge("draft_not_shortlisted", "save")
    g.add_conditional_edges("update_register", c_route_result,
                            {"draft_rejection": "draft_rejection", "draft_hold": "draft_hold"})
    g.add_edge("draft_rejection", "save")
    g.add_edge("draft_hold", "save")
    g.add_edge("save", END)
    return g.compile()


# =====================================================================================
# Onboarding
# =====================================================================================
class OnboardingState(TypedDict, total=False):
    cid: int
    start_status: str
    c: dict
    work_id: int
    drafts: list
    checklist: list
    status: str
    flags: list
    events: list


def o_load(s: OnboardingState) -> OnboardingState:
    c = _snapshot(s["cid"])
    return {"c": c, "start_status": c["status"], "drafts": [], "flags": [], "events": []}


def o_issue_work_id(s: OnboardingState) -> OnboardingState:
    started = time.time()
    _doing("onboarding", "Issuing a work ID")
    had = s["c"]["work_id"]
    wid = db.issue_work_id(s["cid"])
    _record("onboarding", "issue-work-id", s["cid"], started, note=f"Work ID {wid}")
    text = f"Issued work ID {wid}." if not had else f"Kept the existing work ID {wid}."
    return {"work_id": wid, "events": s["events"] + [text]}


def o_draft_acceptance(s: OnboardingState) -> OnboardingState:
    _doing("onboarding", "Writing an acceptance email")
    c = s["c"]
    facts = _facts(c, work_id=str(s["work_id"]))
    d = _draft("onboarding", "draft-acceptance", "acceptance", s["cid"], facts, [c["area"], str(s["work_id"])])
    return {"drafts": [d], "events": s["events"] + [f"Drafted the acceptance email ({d['written_by']})."]}


def o_checklist(s: OnboardingState) -> OnboardingState:
    started = time.time()
    area = db.area_by_name(s["c"]["area"])
    items = tools.induction_checklist(area)
    _record("onboarding", "induction-checklist", s["cid"], started)
    return {"checklist": items, "status": "offer_ready",
            "events": s["events"] + [f"Prepared the induction checklist ({len(items)} items)."]}


def o_save(s: OnboardingState) -> OnboardingState:
    _save_with_drafts("onboarding", s, {"status": s["status"], "checklist": s["checklist"]})
    return {}


def _build_onboarding():
    g = StateGraph(OnboardingState)
    for name, fn in [("load", o_load), ("issue_work_id", o_issue_work_id), ("draft_acceptance", o_draft_acceptance),
                     ("induction_checklist", o_checklist), ("save", o_save)]:
        g.add_node(name, fn)
    g.add_edge(START, "load")
    g.add_edge("load", "issue_work_id")
    g.add_edge("issue_work_id", "draft_acceptance")
    g.add_edge("draft_acceptance", "induction_checklist")
    g.add_edge("induction_checklist", "save")
    g.add_edge("save", END)
    return g.compile()


# =====================================================================================
# Chief of staff
# =====================================================================================
class ChiefState(TypedDict, total=False):
    facts: dict
    stalled: list
    text: str
    written_by: str


def _count(statuses: set[str]) -> int:
    with db.Session() as ses:
        return ses.scalar(select(func.count(db.Candidate.id)).where(db.Candidate.status.in_(statuses))) or 0


def k_read_run_logs(s: ChiefState) -> ChiefState:
    started = time.time()
    since = (datetime.now() - timedelta(hours=24)).replace(microsecond=0).isoformat()
    with db.Session() as ses:
        runs = list(ses.scalars(select(db.Run).where(db.Run.started_at >= since)))
        events = list(ses.scalars(select(db.Event).where(db.Event.at >= since)))
        waiting = ses.scalar(select(func.count(db.Draft.id)).where(db.Draft.status == "waiting")) or 0
    facts = {
        "date": date.today().isoformat(),
        "needs_a_person_today": {
            "areas_to_choose": _count({"needs_area"}),
            "borderline_scores_to_decide": _count({"borderline"}),
            "not_shortlisted_to_confirm": _count({"not_shortlisted_check"}),
            "cvs_that_could_not_be_read": _count({"needs_person"}),
            "emails_waiting_for_release": waiting,
        },
        "total_items_needing_a_person": 0,
        "waiting_for_interview_results": _count({"awaiting_result", "on_hold"}),
        "new_cvs_not_read_yet": _count({"new"}),
        "last_24_hours": {
            "cvs_read": sum(1 for r in runs if r.routine == "parse-cv"),
            "invitations_drafted": sum(1 for e in events if e.text.startswith("Drafted the interview invitation")),
            "work_ids_issued": sum(1 for e in events if e.text.startswith("Issued work ID")),
            "model_steps_fixed_after_a_check": sum(1 for r in runs if r.outcome == "fixed"),
            "model_steps_that_fell_back_to_rules": sum(1 for r in runs if r.outcome == "fallback"),
            "errors": sum(1 for r in runs if r.outcome == "error"),
        },
    }
    facts["total_items_needing_a_person"] = sum(facts["needs_a_person_today"].values())
    _record("chief-of-staff", "read-run-logs", None, started)
    return {"facts": facts}


def k_flag_stalled(s: ChiefState) -> ChiefState:
    started = time.time()
    stalled = []
    for c in db.candidates_in(set(config.STALLED_AFTER_HOURS)):
        limit = config.STALLED_AFTER_HOURS[c.status]
        try:
            age = (datetime.now() - datetime.fromisoformat(c.updated_at)).total_seconds() / 3600
        except ValueError:
            continue
        if age > limit:
            label = config.STATUSES[c.status][0]
            db.add_flag(c.id, f'Stalled: "{label}" for more than {limit} hours.', "Chief of staff")
            stalled.append(c.app_no)
    facts = dict(s["facts"])
    facts["stalled_candidates"] = len(stalled)
    _record("chief-of-staff", "flag-stalled", None, started, note=f"{len(stalled)} stalled")
    return {"facts": facts, "stalled": stalled}


def _template_brief(f: dict) -> str:
    n = f["needs_a_person_today"]
    total = f["total_items_needing_a_person"]
    last = f["last_24_hours"]
    parts = [f"Good morning. Today {total} item(s) need a person."]
    if total:
        parts.append(f"Areas to choose: {n['areas_to_choose']}. Borderline scores: {n['borderline_scores_to_decide']}. "
                     f"Not shortlisted to confirm: {n['not_shortlisted_to_confirm']}. CVs that could not be read: "
                     f"{n['cvs_that_could_not_be_read']}. Emails waiting for release: {n['emails_waiting_for_release']}.")
    parts.append(f"{f['waiting_for_interview_results']} candidate(s) are waiting for an interview result, and "
                 f"{f['new_cvs_not_read_yet']} new CV(s) are not read yet.")
    parts.append(f"In the last 24 hours the AI employees read {last['cvs_read']} CV(s), drafted "
                 f"{last['invitations_drafted']} invitation(s) and issued {last['work_ids_issued']} work ID(s). "
                 f"{last['model_steps_fixed_after_a_check']} model step(s) needed a fix and "
                 f"{last['model_steps_that_fell_back_to_rules']} fell back to rules.")
    if f.get("stalled_candidates"):
        parts.append(f"{f['stalled_candidates']} candidate(s) are stalled and are marked on the Review queue.")
    return " ".join(parts)


def k_morning_brief(s: ChiefState) -> ChiefState:
    started = time.time()
    _doing("chief-of-staff", "Writing the morning brief")
    facts = s["facts"]
    res = ask_checked("chief-of-staff", "morning-brief", _json("FACTS", facts),
                      lambda d: checks.check_brief(d, facts), lambda: _template_brief(facts))
    _record("chief-of-staff", "morning-brief", None, started, res)
    by = {"ok": "AI", "fixed": "AI (fixed after a check)", "fallback": "Template (AI brief failed the checks)"}[res.how]
    with db.Session() as ses:
        ses.add(db.Brief(day=date.today().isoformat(), created_at=db.now(), text=res.value, facts=facts, written_by=by))
        ses.commit()
    db.log_event(None, "Chief of staff", "Wrote the morning brief.")
    return {"text": res.value, "written_by": by}


def _build_chief():
    g = StateGraph(ChiefState)
    g.add_node("read_run_logs", k_read_run_logs)
    g.add_node("flag_stalled", k_flag_stalled)
    g.add_node("morning_brief", k_morning_brief)
    g.add_edge(START, "read_run_logs")
    g.add_edge("read_run_logs", "flag_stalled")
    g.add_edge("flag_stalled", "morning_brief")
    g.add_edge("morning_brief", END)
    return g.compile()


GRAPHS = {"recruiter": _build_recruiter(), "coordinator": _build_coordinator(), "onboarding": _build_onboarding()}
CHIEF_GRAPH = _build_chief()


# =====================================================================================
# Running the employees
# =====================================================================================
def _model_down(e: Exception) -> None:
    NOTICE.update(text=str(e), at=db.now())


def run_employee(key: str, limit: int | None = None, wait: bool = False) -> dict:
    """Let one employee work on the candidates waiting for it."""
    if db.get_setting("paused") == "1":
        return {"employee": key, "done": 0, "skipped": "paused"}
    if not WORK_LOCK.acquire(blocking=wait, timeout=900 if wait else -1):
        return {"employee": key, "done": 0, "skipped": "busy"}
    done = 0
    try:
        for c in db.candidates_in(TRIGGERS[key], limit or config.CANDIDATES_PER_RUN):
            TEAM[key].update(state="working", doing=f"Working on {c.app_no}")
            started = time.time()
            try:
                GRAPHS[key].invoke({"cid": c.id})
                done += 1
                NOTICE.update(text="", at="")
            except llm.ModelUnavailable as e:
                _model_down(e)
                db.log_run(EMPLOYEES[key], "run", c.id, started, time.time() - started, "stopped", 0, str(e))
                break
            except Exception as e:      # keep the other candidates moving
                db.log_run(EMPLOYEES[key], "run", c.id, started, time.time() - started, "error", 0, repr(e)[:500])
                db.add_flag(c.id, f"The {EMPLOYEES[key]} hit an error: {str(e)[:200]}", EMPLOYEES[key])
        TEAM[key].update(last_run=db.now(), last_note=f"{done} candidate(s) handled")
    finally:
        TEAM[key].update(state="idle", doing="")
        WORK_LOCK.release()
    return {"employee": key, "done": done}


def run_chief(wait: bool = True) -> dict:
    if not WORK_LOCK.acquire(blocking=wait, timeout=900 if wait else -1):
        return {"employee": "chief-of-staff", "skipped": "busy"}
    try:
        TEAM["chief-of-staff"].update(state="working", doing="Writing the morning brief")
        try:
            out = CHIEF_GRAPH.invoke({})
            NOTICE.update(text="", at="")
        except llm.ModelUnavailable as e:
            _model_down(e)
            return {"employee": "chief-of-staff", "error": str(e)}
        TEAM["chief-of-staff"].update(last_run=db.now(), last_note="Brief written")
        return {"employee": "chief-of-staff", "written_by": out.get("written_by")}
    finally:
        TEAM["chief-of-staff"].update(state="idle", doing="")
        WORK_LOCK.release()


def run_all_once(limit: int = 20) -> list[dict]:
    """Recruiter, then Coordinator, then Onboarding, each on everything waiting."""
    return [run_employee(k, limit=limit, wait=True) for k in ("recruiter", "coordinator", "onboarding")]


def ask_candidate_cv(cid: int, cv_text: str, profile: dict, question: str) -> dict:
    """Answer a user question grounded strictly in the candidate's CV text."""
    started = time.time()
    task = f"QUESTION:\n{question}\n\n" + _cv_block(cv_text)
    try:
        res = ask_checked(
            "recruiter",
            "ask-cv",
            task,
            lambda d: checks.check_cv_answer(d, cv_text),
            lambda: tools.rule_answer_cv(question, cv_text, profile),
        )
        _record("recruiter", "ask-cv", cid, started, res, note=f"Q: {question[:60]}")
        source = {
            "ok": "AI (checked against the CV)",
            "fixed": "AI (fixed after a CV check)",
            "fallback": "CV search (rules fallback)",
        }[res.how]
        return {"question": question, "answer": res.value["answer"], "quotes": res.value["quotes"], "source": source}
    except llm.ModelUnavailable:
        val = tools.rule_answer_cv(question, cv_text, profile)
        return {"question": question, "answer": val["answer"], "quotes": val["quotes"], "source": "CV search (rules)"}


def start_background(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()
