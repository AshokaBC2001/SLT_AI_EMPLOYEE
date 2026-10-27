# Improvements Report (`feat/improvements`)

**Repository:** `AshokaBC2001/SLT_AI_EMPLOYEE`
**Branch:** `feat/improvements` (also pushed as `thushanth/improvements`). `main` (`d9333a6`) is unchanged.
**Tests:** 40 passing (`.venv/bin/python -m pytest tests -q`), up from 30 on `main`.

Every change follows the project's rule: **the model proposes, plain code decides**. Nothing here changes the
scoring weights, the shortlist thresholds, the work-ID rules, or the fact that no email is ever sent (released
emails are only saved to `data/outbox/`).

---

## 1. Bugs fixed

| # | Problem | Fix | File |
|---|---|---|---|
| 1 | The morning brief check did not stop placeholders like `[Name]` or student email addresses. | `check_brief()` now rejects both, so the model is asked to fix it or the plain-rules brief is used. | `hiring/checks.py` |
| 2 | Renaming an area left existing candidates pointing at the old name. | `save_area()` updates `Candidate.area` for every candidate in the renamed area. | `hiring/actions.py` |
| 3 | Re-drafting an email left the older waiting draft of the same kind in the outbox. | `_save_with_drafts()` marks the older waiting draft of the same kind as `discarded`. | `hiring/flows.py` |
| 4 | Typing an email that another candidate already uses gave no warning. | `set_email()` adds an open note: "Possible duplicate: APP-xxxx has the same email." | `hiring/actions.py` |
| 5 | The Candidates page opened on "Selected candidates", so new CVs looked missing. | The default filter is now "All". The "Selected" filter is handled by the server (`status=selected`). | `web/app.js`, `hiring/server.py` |
| 6 | `.DS_Store` was committed and `.pytest_cache/` was not ignored. | Removed from git and added both to `.gitignore`. | `.gitignore` |

## 2. New features

### 2.1 Ask the CV
- HR officers (candidate page) and Interviewers (interview page) can ask a question about a CV.
- The Recruiter's new `ask-cv` routine (`employees/recruiter/routines/ask-cv/SKILL.md`) returns `{"answer", "quotes"}`.
- `check_cv_answer()` keeps only quotes that `CVText.has()` finds in the CV. This is the same word-based check used
  for profiles and evidence. It matches words, not meaning (see Limits). A failed check goes back to the model; after
  the allowed fixes, `rule_answer_cv()` answers by finding CV lines that contain the question's keywords.
- Ask the CV waits at most 2 seconds for the model. If an employee is using it, the answer comes from the CV by
  plain rules and is labelled "the AI team is busy". So it never runs a second model job at the same time.

### 2.2 Fit across all areas
- `area_fit_matrix()` scores the CV against every active area with the same code-calculated score.
- The candidate page lists each area with its score and the required skills it matched. When the HR officer must
  decide (area unknown, borderline, or low score), a **Use** button switches the candidate to that area.

### 2.3 Clickable induction checklist
- `toggle_checklist()` and `POST /api/candidates/{app_no}/checklist/{index}/toggle` mark items done or not done.
  The card shows "X of Y done" and every change is written to the timeline.

### 2.4 Change the interview slot
- `GET /api/slots` lists free slots; `POST /api/candidates/{app_no}/slot` moves the interview.
- The server only accepts a future working day at one of the set `INTERVIEW_TIMES`, and refuses a slot that is already booked.
- If the invitation is still waiting for release, the date in its text is updated and the draft is checked again.
- If the invitation was already released, a note is added telling the HR officer to inform the student of the new time.

### 2.5 Release all ready emails
- `release_all_ready()` and `POST /api/drafts/release-all` release every waiting email whose candidate is at the
  right step and has a valid address. Others are skipped. As before, released emails are saved to `data/outbox/`, not sent.

### 2.6 CSV export
- `GET /api/candidates.csv` (Export CSV button) downloads the current filter: application number, name, email, area,
  score, status, interview slot, result, work ID, outcome and date added.
- Cells that start with `=`, `+`, `-` or `@` get a leading `'`, so a value from an uploaded CV cannot run as a formula
  in Excel or Google Sheets.

### 2.7 Dashboard funnel and AI team reliability card
- Dashboard: Applied → AI screened → Shortlisted → Interviewed → Selected, counted from the register.
- AI team page: from the run log (`Run` table), the share of model steps that passed first time, needed a fix, or
  fell back to rules, plus the average seconds per model step.

---

## 3. Tested with the real model (Gemma 3 4B)

`ggml-org/gemma-3-4b-it-GGUF:Q4_K_M` was downloaded and run with `llama-server` on an Apple M4 (16 GB).
One sample CV (`kavindu_perera.txt`) went through the whole process: read CV, choose area, questions,
invitation, Ask the CV, Pass, work ID, acceptance email, checklist and morning brief.
**Every model step passed its checks on the first try.** No fixes and no rule fallbacks were needed.

| Step | Seconds (one run) |
|---|---|
| parse-cv | 79–96 |
| choose-area | 87–104 |
| prepare-questions | ~60 |
| invitation | ~45 |
| ask-cv | 52–65 |
| draft-acceptance | ~15 |
| morning-brief | ~48 |

That is roughly **5 minutes of model time per CV** on this machine. Generation ran at about 3–4 tokens/second.
The first request after starting the server was always about twice as fast, and prompt reading then dropped
from ~220 to ~20 tokens/second. The Mac had recorded about 212,000 swap-outs. So the speed depends on how much
memory is free, not on the app.

### Changes from this test
- **`start_model.sh`** now passes `--no-mmproj`. The app only sends text, so the ~850 MB image part of Gemma 3 is
  not loaded. The context size stays at 8192 tokens, which a long CV plus a fix round needs.
- **Quote clean-up:** Gemma often wrapped quotes in extra `"` marks or started them with `- `. `_clean_quote()` removes
  these before quotes are shown or saved. Pass/fail does not change, because `CVText.has()` already ignores punctuation.

### Correction to an earlier version of this report
An earlier commit (`ec1f9c1`) said that switching off llama-server's JSON grammar (`response_format`) on the first
try made the model "more than 2x faster". That came from comparing single runs while the machine's speed was
drifting. A proper test on the same server (6 runs, alternating with and without the grammar) found no gain: the
median was 3.65 tokens/second with the grammar and 3.17 without. The change was reverted, so JSON mode works exactly
as on `main`. The same commit also lowered the context to 4096 tokens and set one slot. These were reverted too,
because a long CV can need more than 4096 tokens.

---

## 4. Tests

`tests/test_core.py` and `tests/test_api.py`: **40 tests, all passing.** They use the scripted fake model, so no
real model is needed. New tests cover:
- the brief rejecting placeholders and emails
- Ask the CV: checked answer, fixed answer, rule fallback, and the answer used while the AI team is busy
- quote clean-up
- the fit-across-areas scores and area rename
- slot changes, including refused past, weekend and off-grid slots, and the note after a released invitation
- the checklist toggle
- the duplicate email note and release-all
- CSV export, including formula-safe cells, and the new API endpoints

## 5. Limits

- Quote and evidence checks match words, not meaning. They prove the words are in the CV, not that the answer is right.
- The rule fallback for Ask the CV returns matching CV lines. It is less fluent than the model.
- The real-model test covered one CV end to end. Run all seven samples before relying on the timings.
