"""The web server: the API for the pages, and the pages themselves (web/ folder).

It only listens on 127.0.0.1, refuses other host names and refuses changes
that come from other websites. Two roles use it, chosen at the top of the page:
"hr" (HR officer) and "interviewer".
"""
from __future__ import annotations

import csv
import io
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from . import actions, config, db, flows, llm, scheduler, tools
from .employees import EMPLOYEES, lessons, role_summary, routines, schedule

VERSION = "1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.setup()
    if config.SCHEDULER_ENABLED:
        scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="SLT AI Employee", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])


@app.middleware("http")
async def same_site_only(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and origin.split("://", 1)[-1].split(":")[0] not in ("localhost", "127.0.0.1"):
            return JSONResponse({"detail": "Requests from other websites are not allowed."}, status_code=403)
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(actions.ActionError)
async def action_error(request: Request, exc: actions.ActionError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


def _role(request: Request) -> str:
    return request.headers.get("x-role", "hr")


def _need_role(request: Request, role: str) -> None:
    if _role(request) != role:
        who = "HR officer" if role == "hr" else "Interviewer"
        raise actions.ActionError(f"Only the {who} can do this. Switch the role at the top right.")


def _kick() -> None:
    """After a person acts, let the employees pick up the work straight away."""
    if config.SCHEDULER_ENABLED and not flows.WORK_LOCK.locked():
        flows.start_background(flows.run_all_once)


# ---- serialising -------------------------------------------------------------------------
def _status(c) -> dict:
    label, chip, actor = config.STATUSES.get(c.status, (c.status, "gray", ""))
    return {"status": c.status, "status_label": label, "chip": chip, "next_actor": actor}


def summary(c: db.Candidate) -> dict:
    return {"app_no": c.app_no, "name": c.name or "(not read yet)", "email": c.email, **_status(c),
            "area": c.area, "suggested_new_area": c.suggested_new_area, "score": c.score,
            "interview_label": c.interview_label, "interview_at": c.interview_at, "result": c.result, "work_id": c.work_id,
            "outcome": c.outcome, "cv_filename": c.cv_filename,
            "open_flags": sum(1 for f in (c.flags or []) if f.get("open")),
            "created_at": c.created_at, "updated_at": c.updated_at}


def _draft_json(d: db.Draft, c: db.Candidate | None = None) -> dict:
    out = {"id": d.id, "kind": d.kind, "kind_label": actions.KIND_LABELS.get(d.kind, d.kind), "subject": d.subject,
           "body": d.body, "status": d.status, "written_by": d.written_by, "check_notes": d.check_notes or [],
           "created_at": d.created_at, "released_at": d.released_at, "file": d.file}
    if c is not None:
        before = actions.RELEASE_MOVES[d.kind][0]
        out.update(app_no=c.app_no, name=c.name, email=c.email, candidate_status=c.status,
                   can_release=(d.status == "waiting" and c.status == before and bool(c.email)),
                   release_blocker="" if c.email else "Add the student's email first.")
    return out


def detail(c: db.Candidate) -> dict:
    with db.Session() as s:
        drafts = list(s.scalars(select(db.Draft).where(db.Draft.candidate_id == c.id).order_by(db.Draft.id)))
        events = list(s.scalars(select(db.Event).where(db.Event.candidate_id == c.id).order_by(db.Event.id)))
        runs = list(s.scalars(select(db.Run).where(db.Run.candidate_id == c.id).order_by(db.Run.id)))
    out = summary(c)
    out.update({
        "email_source": c.email_source, "profile": c.profile or {}, "profile_source": c.profile_source,
        "area_source": c.area_source, "area_reasons": c.area_reasons or [], "area_evidence": c.area_evidence or [],
        "score_parts": c.score_parts or {}, "gaps": c.gaps or [], "questions": c.questions or [],
        "questions_source": c.questions_source, "result_comment": c.result_comment, "result_at": c.result_at,
        "checklist": c.checklist or [],
        "flags": [dict(f, index=i) for i, f in enumerate(c.flags or [])],
        "drafts": [_draft_json(d, c) for d in drafts],
        "events": [{"at": e.at, "actor": e.actor, "text": e.text} for e in events],
        "runs": [{"at": r.started_at, "employee": r.employee, "routine": r.routine, "outcome": r.outcome,
                  "seconds": r.seconds, "model_calls": r.model_calls, "note": r.note} for r in runs],
        "area_matrix": tools.area_fit_matrix(c.profile or {}, c.cv_text or "", db.active_areas()),
        "cv_text": c.cv_text[:config.MAX_CV_CHARS],
    })
    return out


# ---- reading -----------------------------------------------------------------------------
@app.get("/api/meta")
def meta():
    return {"version": VERSION, "statuses": {k: {"label": v[0], "chip": v[1], "next_actor": v[2]}
                                             for k, v in config.STATUSES.items()},
            "weights": config.WEIGHTS, "shortlist_at": config.SHORTLIST_AT, "borderline_at": config.BORDERLINE_AT,
            "model_url": config.MODEL_URL}


@app.get("/api/state")
def state():
    with db.Session() as s:
        counts = dict(s.execute(select(db.Candidate.status, func.count(db.Candidate.id))
                                .group_by(db.Candidate.status)).all())
        waiting = s.scalar(select(func.count(db.Draft.id)).where(db.Draft.status == "waiting")) or 0
        flagged = sum(1 for c in s.scalars(select(db.Candidate).where(db.Candidate.status != "closed",
                                                                       db.Candidate.status.not_in(config.HR_STATUSES)))
                      if any(f.get("open") for f in (c.flags or [])))
        selected = s.scalar(select(func.count(db.Candidate.id)).where(db.Candidate.work_id.is_not(None))) or 0
        interviewed = s.scalar(select(func.count(db.Candidate.id)).where(db.Candidate.result != "")) or 0
        shortlisted_ever = s.scalar(select(func.count(db.Candidate.id)).where(
            (db.Candidate.interview_at != "") | (db.Candidate.status == "shortlisted")
        )) or 0
        recent = list(s.execute(select(db.Event, db.Candidate.app_no, db.Candidate.name)
                                .join(db.Candidate, db.Candidate.id == db.Event.candidate_id, isouter=True)
                                .order_by(db.Event.id.desc()).limit(12)).all())
        by_area = dict(s.execute(select(db.Candidate.area, func.count(db.Candidate.id))
                                 .where(db.Candidate.area != "").group_by(db.Candidate.area)).all())
        brief = s.scalar(select(db.Brief).order_by(db.Brief.id.desc()).limit(1))
        areas = [a.name for a in s.scalars(select(db.Area).where(db.Area.active.is_(True)).order_by(db.Area.id))]
    hr_count = sum(counts.get(k, 0) for k in config.HR_STATUSES)
    total_cands = sum(counts.values())
    return {
        "model": llm.health(), "notice": flows.NOTICE, "paused": db.get_setting("paused") == "1",
        "counts": counts, "total": total_cands,
        "tiles": {"new": counts.get("new", 0), "review": hr_count + flagged, "release": waiting,
                  "interview": counts.get("awaiting_result", 0) + counts.get("on_hold", 0), "selected": selected},
        "funnel": {
            "applied": total_cands,
            "screened": total_cands - counts.get("new", 0),
            "shortlisted": shortlisted_ever,
            "interviewed": interviewed,
            "selected": selected,
        },
        "team": {k: dict(flows.TEAM[k], name=EMPLOYEES[k]) for k in EMPLOYEES},
        "recent": [{"at": e.at, "actor": e.actor, "text": e.text, "app_no": app_no or "", "name": name or ""}
                   for e, app_no, name in recent],
        "areas_chart": [{"area": a, "count": by_area.get(a, 0)} for a in areas] +
                       [{"area": a, "count": n} for a, n in by_area.items() if a not in areas],
        "brief": {"text": brief.text, "created_at": brief.created_at, "written_by": brief.written_by} if brief else None,
    }


def _query_candidates(status: str = "", q: str = "") -> list[db.Candidate]:
    with db.Session() as s:
        query = select(db.Candidate).order_by(db.Candidate.id.desc())
        groups = {"interview": {"awaiting_result", "on_hold"}, "working": {"new", "shortlisted", "not_shortlisted",
                  "failed", "hold", "passed"}}
        if status == "review":
            query = query.where(db.Candidate.status.in_(config.HR_STATUSES))
        elif status == "selected":
            query = query.where(db.Candidate.result == "Pass")
        elif status in groups:
            query = query.where(db.Candidate.status.in_(groups[status]))
        elif status == "release":
            query = query.where(db.Candidate.status.in_(config.RELEASE_STATUSES))
        elif status == "open":
            query = query.where(db.Candidate.status != "closed")
        elif status:
            query = query.where(db.Candidate.status == status)
        rows = list(s.scalars(query))
    if q:
        ql = q.lower()
        rows = [c for c in rows if ql in (c.name or "").lower() or ql in c.app_no.lower()
                or ql in (c.area or "").lower() or ql in (c.email or "").lower()]
    return rows


@app.get("/api/candidates")
def list_candidates(status: str = "", q: str = ""):
    return [summary(c) for c in _query_candidates(status, q)]


@app.get("/api/candidates.csv")
def export_candidates_csv(status: str = "", q: str = ""):
    rows = _query_candidates(status, q)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Application No", "Name", "Email", "Area", "Score", "Status",
                     "Interview Slot", "Result", "Work ID", "Outcome", "Created At"])
    for c in rows:
        label, _, _ = config.STATUSES.get(c.status, (c.status, "gray", ""))
        writer.writerow([c.app_no, c.name, c.email, c.area,
                         "" if c.score is None else c.score, label,
                         c.interview_label, c.result,
                         "" if c.work_id is None else c.work_id,
                         c.outcome, c.created_at])
    return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="slt_candidates.csv"'})


@app.get("/api/slots")
def list_slots():
    return {"slots": actions.free_interview_slots()}


@app.get("/api/candidates/{app_no}")
def get_candidate(app_no: str):
    c = db.get_candidate(app_no)
    if c is None:
        raise actions.ActionError(f"There is no candidate {app_no}.")
    return detail(c)


@app.get("/api/candidates/{app_no}/cv")
def download_cv(app_no: str):
    path, name = actions.cv_file(app_no)
    return FileResponse(path, filename=name)


@app.get("/api/review")
def review():
    with db.Session() as s:
        decisions = list(s.scalars(select(db.Candidate).where(db.Candidate.status.in_(config.HR_STATUSES))
                                   .order_by(db.Candidate.updated_at)))
        open_rows = list(s.scalars(select(db.Candidate).where(db.Candidate.status != "closed")
                                   .order_by(db.Candidate.id)))
        waiting = s.scalar(select(func.count(db.Draft.id)).where(db.Draft.status == "waiting")) or 0
    notes = []
    for c in open_rows:
        if c.status in config.HR_STATUSES:
            continue
        for i, f in enumerate(c.flags or []):
            if f.get("open"):
                notes.append({"app_no": c.app_no, "name": c.name, "index": i, "text": f["text"], "by": f.get("by", ""),
                              "at": f.get("at", ""), **_status(c)})
    suggested: dict[str, list] = {}
    for c in decisions:
        if c.suggested_new_area:
            suggested.setdefault(c.suggested_new_area, []).append(c.app_no)
    reason = {"needs_person": "The CV could not be read.", "needs_area": "Choose the internship area.",
              "borderline": "Score is between 50 and 59. Decide: shortlist or not.",
              "not_shortlisted_check": "Score is below 50. Confirm Not shortlisted, or shortlist instead."}
    return {"decisions": [dict(summary(c), reason=reason[c.status]) for c in decisions], "notes": notes,
            "replies_waiting": waiting,
            "suggested_areas": [{"name": k, "app_nos": v} for k, v in suggested.items()]}


@app.get("/api/drafts")
def list_drafts(state: str = "waiting"):
    with db.Session() as s:
        rows = list(s.execute(select(db.Draft, db.Candidate).join(db.Candidate, db.Candidate.id == db.Draft.candidate_id)
                              .where(db.Draft.status == state).order_by(db.Draft.id.desc())).all())
    return [_draft_json(d, c) for d, c in rows]


@app.get("/api/interviews")
def interviews():
    with db.Session() as s:
        waiting = list(s.scalars(select(db.Candidate).where(db.Candidate.status == "awaiting_result")
                                 .order_by(db.Candidate.interview_at)))
        hold = list(s.scalars(select(db.Candidate).where(db.Candidate.status == "on_hold")
                              .order_by(db.Candidate.interview_at)))
        coming = list(s.scalars(select(db.Candidate).where(db.Candidate.status == "invite_ready")
                                .order_by(db.Candidate.interview_at)))
        done = list(s.scalars(select(db.Candidate).where(db.Candidate.result != "")
                              .order_by(db.Candidate.result_at.desc()).limit(30)))
    return {"waiting": [summary(c) for c in waiting], "on_hold": [summary(c) for c in hold],
            "invitation_not_released": [summary(c) for c in coming], "done": [summary(c) for c in done]}


@app.get("/api/areas")
def list_areas():
    with db.Session() as s:
        rows = list(s.scalars(select(db.Area).order_by(db.Area.id)))
        counts = dict(s.execute(select(db.Candidate.area, func.count(db.Candidate.id))
                                .group_by(db.Candidate.area)).all())
        suggested = dict(s.execute(select(db.Candidate.suggested_new_area, func.count(db.Candidate.id))
                                   .where(db.Candidate.suggested_new_area != "")
                                   .group_by(db.Candidate.suggested_new_area)).all())
    return {"areas": [{"id": a.id, "name": a.name, "description": a.description, "required_skills": a.required_skills,
                       "preferred_skills": a.preferred_skills, "keywords": a.keywords, "checklist": a.checklist,
                       "active": a.active, "added_by": a.added_by, "candidates": counts.get(a.name, 0)} for a in rows],
            "suggested": [{"name": k, "count": v} for k, v in suggested.items()]}


@app.get("/api/team")
def team():
    nxt = scheduler.next_runs()
    since = (datetime.now() - timedelta(hours=24)).replace(microsecond=0).isoformat()
    out = []
    with db.Session() as s:
        all_model_runs = list(s.scalars(select(db.Run).where(db.Run.model_calls > 0)))
        for key, name in EMPLOYEES.items():
            runs = list(s.scalars(select(db.Run).where(db.Run.employee == name).order_by(db.Run.id.desc()).limit(15)))
            day = list(s.scalars(select(db.Run).where(db.Run.employee == name, db.Run.started_at >= since)))
            plan = schedule(key)
            out.append({
                "key": key, "name": name, "summary": role_summary(key), "schedule": plan, "next_run": nxt.get(key, ""),
                "routines": routines(key), "lessons": lessons(key), **flows.TEAM[key],
                "day": {o: sum(1 for r in day if r.outcome == o) for o in ("ok", "fixed", "fallback", "stopped", "error")},
                "runs": [{"at": r.started_at, "routine": r.routine, "outcome": r.outcome, "seconds": r.seconds,
                          "model_calls": r.model_calls, "note": r.note} for r in runs],
            })
    m_total = len(all_model_runs)
    ok_cnt = sum(1 for r in all_model_runs if r.outcome == "ok")
    fix_cnt = sum(1 for r in all_model_runs if r.outcome == "fixed")
    fb_cnt = sum(1 for r in all_model_runs if r.outcome == "fallback")
    benchmark = {
        "total_model_steps": m_total,
        "total_model_calls": sum(r.model_calls for r in all_model_runs),
        "first_pass_pct": round(100 * ok_cnt / m_total) if m_total else 100,
        "verified_pct": round(100 * (ok_cnt + fix_cnt) / m_total) if m_total else 100,
        "self_healed": fix_cnt,
        "fallback": fb_cnt,
        "avg_seconds": round(sum(r.seconds for r in all_model_runs) / m_total, 2) if m_total else 0.0,
    }
    return {"employees": out, "benchmark": benchmark, "paused": db.get_setting("paused") == "1", "model": llm.health(),
            "notice": flows.NOTICE, "scheduler": config.SCHEDULER_ENABLED}


# ---- changing (HR officer) -------------------------------------------------------------------
@app.post("/api/cvs")
async def upload_cvs(request: Request, files: list[UploadFile] = File(...), email: str = Form("")):
    _need_role(request, "hr")
    results = []
    for f in files[:30]:
        data = await f.read(config.MAX_UPLOAD_BYTES + 1)
        results.append(actions.add_cv(f.filename or "cv", data, email if len(files) == 1 else ""))
    if any(r["ok"] for r in results):
        _kick()
    return {"results": results}


@app.post("/api/samples")
def load_samples(request: Request):
    _need_role(request, "hr")
    results = actions.add_samples()
    if any(r["ok"] for r in results):
        _kick()
    return {"results": results}


@app.post("/api/run")
async def run_now(request: Request):
    body = await request.json()
    who = body.get("employee", "all")
    if who == "all":
        flows.start_background(flows.run_all_once)
    elif who == "chief-of-staff":
        flows.start_background(flows.run_chief)
    elif who in flows.TRIGGERS:
        flows.start_background(flows.run_employee, who, 20, True)
    else:
        raise actions.ActionError("Unknown employee.")
    return {"started": who}


@app.post("/api/pause")
async def pause(request: Request):
    _need_role(request, "hr")
    body = await request.json()
    db.set_setting("paused", "1" if body.get("paused") else "0")
    db.log_event(None, "HR officer", "Paused the AI employees." if body.get("paused") else "Resumed the AI employees.")
    return {"paused": bool(body.get("paused"))}


@app.post("/api/candidates/{app_no}/email")
async def set_email(app_no: str, request: Request):
    _need_role(request, "hr")
    actions.set_email(app_no, (await request.json()).get("email", ""))
    return {"ok": True}


@app.post("/api/candidates/{app_no}/area")
async def choose_area(app_no: str, request: Request):
    _need_role(request, "hr")
    out = actions.choose_area(app_no, (await request.json()).get("area", ""))
    _kick()
    return out


@app.post("/api/candidates/{app_no}/decision")
async def decision(app_no: str, request: Request):
    _need_role(request, "hr")
    new = actions.decide(app_no, (await request.json()).get("decision", ""))
    _kick()
    return {"status": new}


@app.post("/api/candidates/{app_no}/retry")
def retry(app_no: str, request: Request):
    _need_role(request, "hr")
    actions.retry(app_no)
    _kick()
    return {"ok": True}


@app.post("/api/candidates/{app_no}/close")
def close(app_no: str, request: Request):
    _need_role(request, "hr")
    actions.close(app_no)
    return {"ok": True}


@app.post("/api/candidates/{app_no}/flags/{index}/resolve")
def resolve_flag(app_no: str, index: int, request: Request):
    _need_role(request, "hr")
    actions.resolve_flag(app_no, index)
    return {"ok": True}


@app.post("/api/candidates/{app_no}/checklist/{index}/toggle")
def toggle_checklist(app_no: str, index: int, request: Request):
    _need_role(request, "hr")
    return {"checklist": actions.toggle_checklist(app_no, index)}


@app.post("/api/candidates/{app_no}/slot")
async def reschedule_slot(app_no: str, request: Request):
    _need_role(request, "hr")
    body = await request.json()
    return actions.reschedule_interview(app_no, body.get("slot_iso", ""))


@app.post("/api/drafts/release-all")
def release_all_drafts(request: Request):
    _need_role(request, "hr")
    return actions.release_all_ready()


@app.post("/api/drafts/{draft_id}")
async def edit_draft(draft_id: int, request: Request):
    _need_role(request, "hr")
    body = await request.json()
    problems = actions.edit_draft(draft_id, body.get("subject", ""), body.get("body", ""))
    return {"check_notes": problems}


@app.post("/api/drafts/{draft_id}/release")
def release(draft_id: int, request: Request):
    _need_role(request, "hr")
    return {"status": actions.release_draft(draft_id)}


@app.post("/api/areas")
async def add_area(request: Request):
    _need_role(request, "hr")
    b = await request.json()
    new_id = actions.save_area(None, b.get("name", ""), b.get("description", ""), b.get("required_skills", ""),
                               b.get("preferred_skills", ""), b.get("keywords", ""), b.get("checklist", ""), True)
    return {"id": new_id}


@app.put("/api/areas/{area_id}")
async def update_area(area_id: int, request: Request):
    _need_role(request, "hr")
    b = await request.json()
    actions.save_area(area_id, b.get("name", ""), b.get("description", ""), b.get("required_skills", ""),
                      b.get("preferred_skills", ""), b.get("keywords", ""), b.get("checklist", ""),
                      b.get("active", True))
    return {"ok": True}


@app.post("/api/brief")
def brief_now(request: Request):
    _need_role(request, "hr")
    flows.start_background(flows.run_chief)
    return {"started": True}


# ---- changing (Interviewer) ------------------------------------------------------------------
@app.post("/api/candidates/{app_no}/result")
async def result(app_no: str, request: Request):
    _need_role(request, "interviewer")
    b = await request.json()
    new = actions.enter_result(app_no, b.get("result", ""), b.get("comment", ""))
    _kick()
    return {"status": new}


@app.post("/api/candidates/{app_no}/ask")
async def ask_candidate_cv(app_no: str, request: Request):
    b = await request.json()
    return actions.ask_cv(app_no, b.get("question", ""))



# ---- the pages -------------------------------------------------------------------------------
app.mount("/", StaticFiles(directory=str(config.WEB_DIR), html=True), name="web")
