"""Tests of the rules, checks and employee flows, using the scripted fake model.

    .venv/bin/python -m pytest tests -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_model import FakeModel  # noqa: E402
from hiring import actions, checks, config, db, employees, flows, llm, tools  # noqa: E402

SAMPLES = config.SAMPLES_DIR


@pytest.fixture()
def fake(tmp_path):
    db.setup(tmp_path / "data")
    model = FakeModel()
    llm.set_backend(model)
    flows.NOTICE.update(text="", at="")
    yield model
    llm.set_backend(None)


def add(name: str, email: str = "") -> str:
    p = SAMPLES / name
    r = actions.add_cv(p.name, p.read_bytes(), email)
    assert r["ok"], r
    return r["app_no"]


def cand(app_no):
    return db.get_candidate(app_no)


# ---------------------------------------------------------------- checks
CV = (SAMPLES / "kavindu_perera.txt").read_text()


def test_profile_check_removes_items_not_in_the_cv():
    data = {"name": "Kavindu Perera", "email": "kavindu.perera@example.com", "phone": "+94 71 000 1122",
            "education": ["BSc (Hons) in Data Science, Sri Lanka Technological Campus"],
            "skills": ["Python", "Pandas", "Kubernetes"], "projects": [], "experience": []}
    clean, problems, removed = checks.check_profile(data, CV)
    assert problems == []
    assert removed == ["Kubernetes"]
    assert "Kubernetes" not in clean["skills"] and "Python" in clean["skills"]


def test_profile_check_rejects_invented_name_and_email():
    clean, problems, _ = checks.check_profile({"name": "John Invented", "email": "fake@nowhere.com"}, CV)
    assert any("name" in p for p in problems)
    assert any("email" in p for p in problems)


def test_area_check_needs_evidence_from_the_cv():
    names = ["AI/ML", "DevOps"]
    good, problems = checks.check_area({"area": "machine learning", "reasons": ["Strong ML"], "evidence": ["Scikit-learn"]}, names, CV)
    assert problems == [] and good["area"] == "AI/ML"
    _, problems = checks.check_area({"area": "DevOps", "reasons": ["x"], "evidence": ["Kubernetes expert at Google"]}, names, CV)
    assert any("evidence" in p for p in problems)


def test_area_check_new_area_and_needs_review():
    r, _ = checks.check_area({"area": "New area: Human Resources", "reasons": ["HR"], "evidence": ["Python"]}, ["AI/ML"], CV)
    assert r["new_area"] == "Human Resources" and r["area"] == ""
    r, problems = checks.check_area({"area": "Needs human review", "reasons": ["unsure"], "evidence": []}, ["AI/ML"], CV)
    assert r["area"] == config.NEEDS_REVIEW_AREA and problems == []


def test_draft_check_catches_placeholders_numbers_and_missing_facts():
    facts = {"name": "Kavindu Perera", "area": "AI/ML", "app_no": "APP-0002", "interview": "Friday 23 October 2026 at 10:15"}
    bad = {"subject": "Hi", "body": "Dear [Name], come within 14 days for the interview. " * 3}
    _, problems = checks.check_draft(bad, facts, ["AI/ML", facts["interview"]])
    text = " ".join(problems)
    assert "placeholder" in text and "14" in text and "Kavindu" in text and "AI/ML" in text
    good = tools.template_draft("invitation", facts)
    _, problems = checks.check_draft(good, facts, ["AI/ML", facts["interview"]])
    assert problems == []


def test_brief_check_rejects_invented_numbers():
    _, problems = checks.check_brief({"brief": "Good morning. 999 students applied. " * 4}, {"a": 3})
    assert any("999" in p for p in problems)


# ---------------------------------------------------------------- scoring
def test_scoring_uses_the_weights_and_finds_gaps(fake):
    area = db.area_by_name("DevOps")
    text = tools.read_cv(SAMPLES / "ishara_silva.txt")
    profile = tools.rule_profile(text, tools.skill_vocabulary(db.active_areas()))
    score, parts, gaps = tools.score_cv(profile, text, area)
    assert parts["skills"]["max"] == 40 and parts["projects"]["max"] == 30
    assert parts["education"]["max"] == 20 and parts["experience"]["max"] == 10
    assert sorted(gaps) == ["Bash", "CI/CD", "Cloud"]
    assert score == sum(p["points"] for p in parts.values()) or abs(score - sum(p["points"] for p in parts.values())) <= 2
    assert tools.shortlist_status(score) == "borderline"


def test_shortlist_thresholds():
    assert tools.shortlist_status(60) == "shortlisted"
    assert tools.shortlist_status(59) == "borderline"
    assert tools.shortlist_status(50) == "borderline"
    assert tools.shortlist_status(49) == "not_shortlisted_check"


# ---------------------------------------------------------------- work IDs
def _to_status(app_no, status, email=None):
    c = cand(app_no)
    fields = {"status": status}
    if email is not None:
        fields["email"] = email
    db.update_candidate(c.id, **fields)
    return c.id


def test_work_id_rules(fake):
    a = add("kavindu_perera.txt")
    b = add("sanduni_fernando.txt")
    cid_a = _to_status(a, "shortlisted")
    with pytest.raises(PermissionError):
        db.issue_work_id(cid_a)                      # only after Pass
    _to_status(a, "passed")
    assert db.issue_work_id(cid_a) == 1001
    assert db.issue_work_id(cid_a) == 1001           # asking again gives the same ID
    cid_b = _to_status(b, "passed", email="other@example.com")
    assert db.issue_work_id(cid_b) == 1002           # counts up
    # a new application from the same email gets the same ID
    p = SAMPLES / "kavindu_perera.txt"
    r = actions.add_cv("again.txt", p.read_bytes() + b"\nUpdated CV", "kavindu.perera@example.com")
    _to_status(a, "passed", email="kavindu.perera@example.com")
    cid_c = _to_status(r["app_no"], "passed")
    assert db.issue_work_id(cid_c) == 1001
    assert db.get_setting("next_work_id") == "1003"  # never reused


# ---------------------------------------------------------------- employee files
def test_employee_folders_are_complete():
    for key in employees.EMPLOYEES:
        assert employees.role_text(key)
        assert employees.role_summary(key)
        plan = employees.schedule(key)
        assert plan["every_seconds"] or plan["daily_at"]
        for r in employees.routines(key):
            if r["uses_model"]:
                assert "JSON" in employees.instructions(key, r["name"])


# ---------------------------------------------------------------- Recruiter
def test_recruiter_reads_scores_and_shortlists(fake):
    a = add("kavindu_perera.txt")
    flows.run_employee("recruiter", wait=True)
    c = cand(a)
    assert c.status == "shortlisted" and c.area == "AI/ML" and c.score >= 60
    assert c.email == "kavindu.perera@example.com" and c.email_source == "Read from CV"
    assert c.area_evidence and all(checks.CVText(c.cv_text).has(e) for e in c.area_evidence)


def test_recruiter_fixes_a_bad_answer(fake):
    fake.bad["parse-cv"] = 1
    a = add("kavindu_perera.txt")
    flows.run_employee("recruiter", wait=True)
    c = cand(a)
    assert c.profile_source == "AI" and c.name == "Kavindu Perera"
    with db.Session() as s:
        from sqlalchemy import select
        outcomes = [r.outcome for r in s.scalars(select(db.Run).where(db.Run.routine == "parse-cv"))]
    assert outcomes == ["fixed"]
    assert employees.lessons("recruiter")            # learned a lesson
    assert "Kavindu" not in (db.paths.notes / "recruiter.md").read_text()   # no personal data in lessons


def test_recruiter_falls_back_to_rules_and_flags(fake):
    fake.bad["parse-cv"] = 5
    fake.bad["choose-area"] = 5
    a = add("sanduni_fernando.txt")
    flows.run_employee("recruiter", wait=True)
    c = cand(a)
    assert c.profile_source == "Rules"
    assert c.area == "DevOps" and c.area_source == "Chosen by rules"
    assert any("simple rules" in f["text"] for f in c.flags)


def test_hr_cv_gets_a_new_area_suggestion_not_forced_into_it(fake):
    a = add("tharushi_madushani.pdf")
    flows.run_employee("recruiter", wait=True)
    c = cand(a)
    assert c.status == "needs_area" and c.area == "" and c.suggested_new_area == "Human Resources"
    actions.save_area(None, "Human Resources", "", "Recruitment, Interviewing, Communication", "", "", "")
    out = actions.choose_area(a, "Human Resources")
    assert out["status"] == "shortlisted" and cand(a).area_source == "Chosen by HR officer"


def test_borderline_goes_to_the_hr_officer(fake):
    a = add("ishara_silva.txt")
    flows.run_employee("recruiter", wait=True)
    assert cand(a).status == "borderline"
    flows.run_employee("coordinator", wait=True)
    assert cand(a).status == "borderline"            # the Coordinator does not touch it
    actions.decide(a, "shortlist")
    assert cand(a).status == "shortlisted"


def test_unreadable_cv_needs_a_person(fake):
    r = actions.add_cv("scan.txt", b"   \n  ")
    assert r["ok"]
    flows.run_employee("recruiter", wait=True)
    assert cand(r["app_no"]).status == "needs_person"


def test_model_down_stops_without_changing_anything(fake):
    a = add("kavindu_perera.txt")

    def down(messages, json_mode):
        raise llm.ModelUnavailable("The model server is not running.")
    llm.set_backend(down)
    flows.run_employee("recruiter", wait=True)
    assert cand(a).status == "new"
    assert "not running" in flows.NOTICE["text"]


# ---------------------------------------------------------------- whole flows
def _release_waiting(app_no):
    with db.Session() as s:
        from sqlalchemy import select
        d = s.scalar(select(db.Draft).where(db.Draft.candidate_id == cand(app_no).id, db.Draft.status == "waiting"))
    return actions.release_draft(d.id)


def test_pass_flow_end_to_end(fake):
    a = add("kavindu_perera.txt")
    flows.run_all_once()
    c = cand(a)
    assert c.status == "invite_ready" and c.interview_label and len(c.questions) >= 4
    with pytest.raises(actions.ActionError):
        actions.enter_result(a, "Pass")              # invitation not released yet
    assert _release_waiting(a) == "awaiting_result"
    assert list(db.paths.outbox.glob("*.txt"))       # saved, not sent
    actions.enter_result(a, "Pass", "Good")
    flows.run_all_once()
    c = cand(a)
    assert c.status == "offer_ready" and c.work_id == 1001 and c.checklist
    assert _release_waiting(a) == "closed"
    assert cand(a).outcome.startswith("Selected")


def test_fail_and_hold_flows(fake):
    a = add("sanduni_fernando.txt")
    b = add("ruwan_jayasinghe.txt")
    flows.run_all_once()
    _release_waiting(a)
    _release_waiting(b)
    actions.enter_result(a, "Fail")
    actions.enter_result(b, "Hold")
    flows.run_all_once()
    assert cand(a).status == "reply_ready" and cand(a).work_id is None
    assert cand(b).status == "hold_note_ready"
    _release_waiting(a)
    _release_waiting(b)
    assert cand(a).status == "closed" and cand(b).status == "on_hold"
    with pytest.raises(actions.ActionError):
        actions.enter_result(b, "Hold")              # from On hold only Pass or Fail
    actions.enter_result(b, "Pass")
    flows.run_all_once()
    assert cand(b).work_id == 1001


def test_not_shortlisted_needs_confirmation_then_reply(fake):
    a = add("nimal_bandara.txt")
    flows.run_employee("recruiter", wait=True)
    assert cand(a).status == "needs_area"
    out = actions.choose_area(a, "AI/ML")
    assert out["status"] == "not_shortlisted_check"
    flows.run_employee("coordinator", wait=True)
    assert cand(a).status == "not_shortlisted_check"  # no reply before the HR officer confirms
    actions.decide(a, "confirm")
    flows.run_employee("coordinator", wait=True)
    assert cand(a).status == "reply_ready"


def test_bad_drafts_fall_back_to_the_template(fake):
    fake.bad["invite-and-slots"] = 5
    a = add("kavindu_perera.txt")
    flows.run_all_once()
    with db.Session() as s:
        from sqlalchemy import select
        d = s.scalar(select(db.Draft).where(db.Draft.candidate_id == cand(a).id))
    assert d.written_by.startswith("Template")
    assert "[Name]" not in d.body and cand(a).interview_label in d.body


def test_release_needs_an_email(fake):
    p = SAMPLES / "kavindu_perera.txt"
    text = p.read_text().replace("kavindu.perera@example.com | ", "")
    r = actions.add_cv("no_email.txt", text.encode())
    flows.run_all_once()
    c = cand(r["app_no"])
    assert c.email == "" and any("No email" in f["text"] for f in c.flags)
    with pytest.raises(actions.ActionError):
        _release_waiting(r["app_no"])
    actions.set_email(r["app_no"], "k.perera@example.com")
    assert _release_waiting(r["app_no"]) == "awaiting_result"


def test_morning_brief(fake):
    add("kavindu_perera.txt")
    flows.run_all_once()
    out = flows.run_chief()
    assert out["written_by"] in ("AI", "AI (fixed after a check)")
    fake.bad["morning-brief"] = 5
    out = flows.run_chief()
    assert out["written_by"].startswith("Template")


def test_duplicate_upload_is_refused(fake):
    add("kavindu_perera.txt")
    p = SAMPLES / "kavindu_perera.txt"
    r = actions.add_cv(p.name, p.read_bytes())
    assert not r["ok"] and "already added" in r["reason"]
    assert not actions.add_cv("cv.exe", b"x")["ok"]
    assert not actions.add_cv("big.txt", b"x" * (config.MAX_UPLOAD_BYTES + 1))["ok"]


def test_reschedule_interview_and_checklist_toggle(fake):
    a = add("kavindu_perera.txt")
    flows.run_all_once()
    slots = actions.free_interview_slots(count=5)
    assert len(slots) == 5
    new_slot = slots[1]
    res = actions.reschedule_interview(a, new_slot["iso"])
    assert res["interview_label"] == new_slot["label"]
    with db.Session() as s:
        from sqlalchemy import select
        d = s.scalar(select(db.Draft).where(db.Draft.candidate_id == cand(a).id, db.Draft.status == "waiting"))
    assert new_slot["label"] in d.body
    _release_waiting(a)
    actions.enter_result(a, "Pass")
    flows.run_all_once()
    items = actions.toggle_checklist(a, 0)
    assert items[0]["done"] is True
    items = actions.toggle_checklist(a, 0)
    assert items[0]["done"] is False


def test_set_email_flags_duplicate_and_release_all(fake):
    a = add("kavindu_perera.txt")
    b = add("sanduni_fernando.txt")
    flows.run_all_once()
    actions.set_email(b, "kavindu.perera@example.com")
    assert any("Possible duplicate" in f["text"] and f["open"] for f in cand(b).flags)
    res = actions.release_all_ready()
    assert res["released"] == 2
    assert cand(a).status == "awaiting_result" and cand(b).status == "awaiting_result"


def test_ask_cv_and_area_fit_matrix_and_area_rename(fake):
    a = add("kavindu_perera.txt")
    flows.run_employee("recruiter", wait=True)
    c = cand(a)
    matrix = tools.area_fit_matrix(c.profile, c.cv_text, db.active_areas())
    assert len(matrix) == 4 and matrix[0]["area"] == "AI/ML" and matrix[0]["score"] >= 60

    ans = actions.ask_cv(a, "Summarize key strengths")
    assert ans["answer"] and ans["quotes"] and "AI" in ans["source"]
    assert all(checks.CVText(c.cv_text).has(q) for q in ans["quotes"])

    # Self-healing when model initially invents a quote not in CV
    fake.bad["ask-cv"] = 1
    ans_fixed = actions.ask_cv(a, "What projects did this student build?")
    assert "fixed" in ans_fixed["source"]

    # Fallback when model keeps failing checks
    fake.bad["ask-cv"] = 5
    ans_fb = actions.ask_cv(a, "Does the CV mention Python and Scikit-learn?")
    assert "rules" in ans_fb["source"] and ans_fb["quotes"]

    # Renaming an area updates existing candidates in that area
    ai_area = db.area_by_name("AI/ML")
    actions.save_area(ai_area.id, "AI & ML", ai_area.description, ai_area.required_skills,
                      ai_area.preferred_skills, ai_area.keywords, ai_area.checklist, True)
    assert cand(a).area == "AI & ML"


def test_brief_check_rejects_placeholders_and_emails():
    _, problems = checks.check_brief(
        {"brief": "Good morning [Name]. Contact student@example.com for the 3 items today. " * 3},
        {"a": 3},
    )
    text = " ".join(problems)
    assert "placeholder" in text and "email" in text



def test_reschedule_refuses_bad_slots_and_flags_released_invitations(fake):
    a = add("kavindu_perera.txt")
    flows.run_all_once()
    # Past dates, weekends and times outside the interview grid are refused.
    for bad in ("2020-01-06T09:30", "2099-01-03T09:30", "2099-01-05T08:00", "not a date"):
        with pytest.raises(actions.ActionError):
            actions.reschedule_interview(a, bad)
    # After the invitation is released, moving the slot leaves a note to tell the student.
    _release_waiting(a)
    slot = actions.free_interview_slots(count=3)[2]
    actions.reschedule_interview(a, slot["iso"])
    assert any("tell the student" in f["text"] and f["open"] for f in cand(a).flags)


def test_quotes_are_cleaned_of_extra_marks():
    data = {"answer": "The student built a churn model with Scikit-learn and Pandas.",
            "quotes": ['"built a classification model with Scikit-learn and Pandas"', "- Customer churn prediction"]}
    clean, problems = checks.check_cv_answer(data, CV)
    assert problems == []
    assert clean["quotes"][0].startswith("built") and clean["quotes"][1].startswith("Customer")


def test_ask_cv_does_not_wait_while_the_ai_team_is_busy(fake):
    a = add("kavindu_perera.txt")
    flows.run_employee("recruiter", wait=True)
    assert flows.WORK_LOCK.acquire(timeout=1)
    try:
        ans = actions.ask_cv(a, "Does the CV mention Python?")
    finally:
        flows.WORK_LOCK.release()
    assert "busy" in ans["source"] and ans["quotes"]


def test_csv_cells_cannot_run_as_formulas():
    from hiring.server import _csv_safe
    assert _csv_safe('=HYPERLINK("http://x")') == '\'=HYPERLINK("http://x")'
    assert _csv_safe("@SUM(A1)") == "'@SUM(A1)"
    assert _csv_safe("Kavindu Perera") == "Kavindu Perera"
    assert _csv_safe(72) == 72
