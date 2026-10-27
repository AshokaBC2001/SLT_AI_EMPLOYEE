"""Tests of the web API (roles, safety and the main actions), with the fake model."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_model import FakeModel  # noqa: E402
from hiring import config, db, flows, llm  # noqa: E402
from hiring.server import app  # noqa: E402

HR = {"x-role": "hr"}
IN = {"x-role": "interviewer"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCHEDULER_ENABLED", False)
    db.setup(tmp_path / "data")
    llm.set_backend(FakeModel())
    with TestClient(app) as c:
        yield c
    llm.set_backend(None)


def test_pages_and_state(client):
    assert client.get("/").status_code == 200
    assert "app.js" in client.get("/").text
    s = client.get("/api/state").json()
    assert s["model"]["ok"] and s["total"] == 0


def test_upload_and_flow(client):
    p = config.SAMPLES_DIR / "kavindu_perera.txt"
    r = client.post("/api/cvs", headers=HR, files=[("files", (p.name, p.read_bytes(), "text/plain"))],
                    data={"email": "k@example.com"}).json()
    assert r["results"][0]["ok"]
    app_no = r["results"][0]["app_no"]
    flows.run_all_once()
    d = client.get(f"/api/candidates/{app_no}").json()
    assert d["status"] == "invite_ready" and d["email"] == "k@example.com"
    draft = d["drafts"][0]
    assert draft["can_release"]
    assert client.post(f"/api/drafts/{draft['id']}/release", headers=HR).json()["status"] == "awaiting_result"
    assert client.get("/api/interviews").json()["waiting"][0]["app_no"] == app_no
    assert client.post(f"/api/candidates/{app_no}/result", headers=IN, json={"result": "Pass"}).status_code == 200


def test_roles_are_enforced(client):
    client.post("/api/samples", headers=HR)
    flows.run_all_once()
    rows = client.get("/api/candidates?status=release").json()
    app_no = rows[0]["app_no"]
    d = client.get(f"/api/candidates/{app_no}").json()["drafts"][0]
    r = client.post(f"/api/drafts/{d['id']}/release", headers=IN)
    assert r.status_code == 400 and "HR officer" in r.json()["detail"]
    client.post(f"/api/drafts/{d['id']}/release", headers=HR)
    r = client.post(f"/api/candidates/{app_no}/result", headers=HR, json={"result": "Pass"})
    assert r.status_code == 400 and "Interviewer" in r.json()["detail"]


def test_other_websites_and_hosts_are_refused(client):
    assert client.post("/api/samples", headers={**HR, "origin": "http://evil.example"}).status_code == 403
    assert client.get("/api/state", headers={"host": "evil.example"}).status_code == 400


def test_bad_input_gives_a_clear_message(client):
    r = client.post("/api/cvs", headers=HR, files=[("files", ("x.exe", b"abc", "application/octet-stream"))]).json()
    assert not r["results"][0]["ok"]
    assert client.get("/api/candidates/APP-9999").status_code == 400
    assert client.get("/api/candidates/..%2F..%2Fetc/cv").status_code in (400, 404)
    r = client.post("/api/areas", headers=HR, json={"name": "Empty area", "required_skills": ""})
    assert r.status_code == 400 and "required skill" in r.json()["detail"]


def test_review_lists_decisions_and_suggested_areas(client):
    client.post("/api/samples", headers=HR)
    flows.run_employee("recruiter", limit=20, wait=True)
    r = client.get("/api/review").json()
    statuses = {d["status"] for d in r["decisions"]}
    assert {"needs_area", "borderline"} <= statuses
    assert any(s["name"] == "Human Resources" for s in r["suggested_areas"])
    team = client.get("/api/team").json()
    assert len(team["employees"]) == 4


def test_csv_export_reschedule_checklist_and_release_all(client):
    client.post("/api/samples", headers=HR)
    flows.run_all_once()
    slots = client.get("/api/slots").json()["slots"]
    assert len(slots) > 2
    rows = client.get("/api/candidates?status=release").json()
    app_no = rows[0]["app_no"]
    r_slot = client.post(f"/api/candidates/{app_no}/slot", headers=HR, json={"slot_iso": slots[0]["iso"]})
    assert r_slot.status_code == 200 and r_slot.json()["interview_label"] == slots[0]["label"]
    r_rel = client.post("/api/drafts/release-all", headers=HR).json()
    assert r_rel["released"] >= 4
    client.post(f"/api/candidates/{app_no}/result", headers=IN, json={"result": "Pass", "comment": "Strong"})
    flows.run_all_once()
    r_chk = client.post(f"/api/candidates/{app_no}/checklist/0/toggle", headers=HR)
    assert r_chk.status_code == 200 and r_chk.json()["checklist"][0]["done"] is True
    selected = client.get("/api/candidates?status=selected").json()
    assert len(selected) == 1 and selected[0]["app_no"] == app_no
    csv_resp = client.get("/api/candidates.csv?status=selected")
    assert csv_resp.status_code == 200 and "text/csv" in csv_resp.headers["content-type"]
    assert app_no in csv_resp.text and "1001" in csv_resp.text


def test_ask_cv_area_matrix_funnel_and_benchmark_endpoints(client):
    client.post("/api/samples", headers=HR)
    flows.run_all_once()
    rows = client.get("/api/candidates").json()
    app_no = rows[0]["app_no"]
    detail = client.get(f"/api/candidates/{app_no}").json()
    assert len(detail["area_matrix"]) == 4

    r_ask = client.post(f"/api/candidates/{app_no}/ask", headers=IN, json={"question": "Summarize key strengths"})
    assert r_ask.status_code == 200
    body = r_ask.json()
    assert body["answer"] and isinstance(body["quotes"], list)

    st = client.get("/api/state").json()
    assert st["funnel"]["applied"] == 7 and st["funnel"]["screened"] == 7

    tm = client.get("/api/team").json()
    assert tm["benchmark"]["total_model_steps"] > 0
    assert tm["benchmark"]["verified_pct"] == 100


