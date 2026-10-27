# Engineering Audit & Improvements Report (`feat/improvements`)

**Repository:** `AshokaBC2001/SLT_AI_EMPLOYEE`  
**Branch:** `feat/improvements` (base branch `main` at `d9333a6` remains untouched)  
**Test Suite Status:** **36 / 36 passing** (`pytest tests -q`)  

---

## 1. Executive Summary

We conducted a full-stack audit of the **SLT AI Employee (Hiring Desk)** repository across its Python backend (`hiring/`), vanilla JS single-page frontend (`web/`), employee routine specifications (`employees/`), and automated test suite (`tests/`).

In alignment with the project's core architectural rule—**"The model proposes, plain code decides"**—we:
1. Resolved **6 edge-case bugs and guardrail gaps** across privacy checks, data consistency, draft lifecycle management, and UI navigation.
2. Built **7 high-value product features and innovations** that elevate the system from a static pipeline into an interactive, citation-grounded AI recruiting workbench.
3. Expanded the automated unit and API test suite from **30 to 36 tests**, verifying both happy paths and guardrail rejection paths.

---

## 2. Bugs & Edge Cases Fixed

### 2.1 Morning Brief Privacy & Placeholder Guardrail (`hiring/checks.py`)
- **Issue:** `check_brief()` validated line counts, candidate names, and stage words, but did not check whether the language model leaked raw candidate email addresses or left template placeholders (`[insert]`, `{{name}}`, `TBD`) in the daily summary.
- **Fix:** Added `PLACEHOLDER_RE` and `EMAIL_RE` validation inside `check_brief()` so any leaked email address or unfilled bracket placeholder triggers an immediate retry or deterministic fallback.

### 2.2 Cascading Area Renames (`hiring/actions.py`)
- **Issue:** When a hiring manager edited an existing hiring area's name in `save_area()`, candidates already assigned to that area kept the old string in `Candidate.area`, causing subsequent evaluations to fall back to the default area.
- **Fix:** Recorded the previous area title before updating and cascaded the rename across all matching candidate records in the same transaction.

### 2.3 Superseded Waiting Email Draft Cleanup (`hiring/flows.py`)
- **Issue:** Re-running an action on a candidate (such as re-scoring a CV or changing an interview outcome before releasing the previous email) appended a new draft to `state.drafts` while leaving the older waiting draft of the same `kind` active in the outbox.
- **Fix:** Updated `_save_with_drafts()` to automatically mark older `waiting` drafts for the same `(app_no, kind)` as `discarded` whenever a newer replacement draft is queued.

### 2.4 Duplicate Email Warning on Manual Edit (`hiring/actions.py`)
- **Issue:** Duplicate detection only ran during initial CV upload, allowing a manager to manually assign an existing candidate's email address to another application in `set_email()` without warning.
- **Fix:** Added cross-candidate email normalisation and conflict checking in `set_email()`, appending an explicit warning note if the address belongs to another application.

### 2.5 Candidate List Filter Reset (`web/app.js`)
- **Issue:** Clicking "Candidates" (`#/candidates`) in the left sidebar after viewing a filtered link (such as `#/candidates?status=hold` from the dashboard) preserved the old filter state because query parameter parsing only updated properties when present.
- **Fix:** Reset `ui.filterStatus` and `ui.filterArea` whenever `#/candidates` is navigated to without query parameters, and added support for the `status=selected` filter group in `_query_candidates()`.

### 2.6 Repository Hygiene (`.gitignore`)
- **Issue:** macOS `.DS_Store` metadata was tracked in git and `.pytest_cache/` was not ignored.
- **Fix:** Removed `.DS_Store` from tracking and added `.DS_Store` and `.pytest_cache/` to `.gitignore`.

---

## 3. New Features & Innovations

### 3.1 Citation-Grounded "Ask the CV" Assistant
- **Files:** `employees/recruiter/routines/ask-cv/SKILL.md`, `hiring/employees.py`, `hiring/checks.py`, `hiring/tools.py`, `hiring/flows.py`, `hiring/actions.py`, `hiring/server.py`, `web/app.js`
- **How it works:** Recruiters can ask natural-language questions directly on any candidate's profile (e.g., *"What cloud or Docker experience do they have?"*).
- **Guardrail:** The Recruiter routine returns JSON with `answer`, `quotes`, and `found`. `check_cv_answer()` verifies that every quote is an **exact substring** of the candidate's CV via `CVText.has()`. If the model fabricates a quote or is offline, `rule_answer_cv()` deterministically searches CV lines for matching keywords and returns verified quotes.

### 3.2 Multi-Area Fit Matrix & One-Click Role Switching
- **Files:** `hiring/tools.py`, `hiring/server.py`, `web/app.js`
- **How it works:** `area_fit_matrix()` evaluates a candidate's CV against **all active hiring areas simultaneously**, displaying a side-by-side comparison of scores, matched skills, and pass/borderline/fail badges on the candidate detail page.
- **Impact:** If an applicant for *Software Engineering* is actually a stronger match for *Data & AI*, the recruiter sees a `"Best match"` badge and can click **"Switch to area"** to re-route and re-evaluate the candidate in one click.

### 3.3 Interactive Onboarding Checklist
- **Files:** `hiring/actions.py`, `hiring/server.py`, `web/app.js`
- **How it works:** Added `toggle_checklist()` and `POST /api/candidates/{app_no}/checklist/{index}/toggle` so HR coordinators can click onboarding tasks on the candidate profile to mark them `"done"` or `"todo"`, with a live progress counter (`X/Y done`) and audit log entry.

### 3.4 Interview Slot Rescheduling with Auto-Updated Drafts
- **Files:** `hiring/tools.py`, `hiring/actions.py`, `hiring/server.py`, `web/app.js`
- **How it works:** Added `upcoming_interview_slots()`, `reschedule_interview()`, `GET /api/slots`, and `POST /api/candidates/{app_no}/slot`. Managers can move an invited candidate to any free upcoming interview slot without collisions; any waiting `invite_interview` draft in the outbox automatically updates its date/time text and subject line.

### 3.5 Batch "Release All Ready" in Email Outbox
- **Files:** `hiring/actions.py`, `hiring/server.py`, `web/app.js`
- **How it works:** Added `release_all_ready()` and `POST /api/drafts/release-all` along with a **"Release all ready (N)"** button on the Replies page so managers can send all clean, guardrail-verified emails in a single action while holding drafts with missing recipient addresses.

### 3.6 One-Click Candidate CSV Export
- **Files:** `hiring/server.py`, `web/app.js`
- **How it works:** Added `GET /api/candidates.csv` and an **"Export CSV"** button on the Candidates page to download the full candidate pipeline (application number, status, score, matched skills, interview slot, outcome, and onboarding progress) as a spreadsheet.

### 3.7 Live Hiring Pipeline Funnel & AI Guardrail Reliability Benchmark
- **Files:** `hiring/server.py`, `web/app.js`
- **How it works:**
  - **Dashboard Funnel:** Visualizes real-time candidate progression across *Total CVs → Passed Screen → Interview Invited → Selected / Handed Off → On Hold*.
  - **AI Team Benchmark Card:** Computes live telemetry from `state.runs` showing first-pass guardrail rate, deterministic fallback rate, and average latency across all AI employee routines.

---

## 4. Verification & Test Coverage

All existing and new features are covered by automated tests in `tests/test_core.py` and `tests/test_api.py` (36 total passing tests):
- `test_brief_check_rejects_placeholders_and_emails`
- `test_ask_cv_and_area_fit_matrix_and_area_rename`
- `test_reschedule_interview_and_checklist_toggle`
- `test_set_email_flags_duplicate_and_release_all`
- `test_csv_export_reschedule_checklist_and_release_all`
- `test_ask_cv_area_matrix_funnel_and_benchmark_endpoints`

Run the full test suite locally with:
```bash
.venv/bin/python -m pytest tests -q
```
