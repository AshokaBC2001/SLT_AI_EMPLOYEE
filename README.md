# SLT AI Employee: intern hiring

A hiring system for SLT interns. Four **AI employees** do the office work, and two **people** make the decisions:

| Who | What they do |
|---|---|
| **Recruiter** (AI) | Reads each CV, writes a profile that is checked against the CV, chooses the internship area and scores the match. |
| **Coordinator** (AI) | Books the interview slot, prepares the interviewer's questions and drafts every email to students. |
| **Onboarding** (AI) | After a Pass, issues the 4-digit work ID, drafts the acceptance email and prepares the induction checklist. |
| **Chief of staff** (AI) | Every morning, reads what the team did, flags stalled work and writes a short brief. |
| **HR officer** (person) | Adds CVs, decides borderline and low scores, chooses areas the AI is unsure about, adds new areas, releases every email. |
| **Interviewer** (person) | Does the interview and enters Pass, Fail or Hold. The AI can never change this result. |

Everything runs on your own Mac. The model is **Gemma 3 4B**, run by **llama.cpp** (no Ollama). CVs never leave the computer and **no email is sent**: a released email is saved as a file in `data/outbox/`.

---

## 1. One-time setup (Mac)

You need Homebrew and Python 3.10 or newer (`python3 --version`).

```bash
brew install llama.cpp
```

Unzip `SLT_AI_EMPLOYEE.zip`, then in the terminal:

```bash
cd ~/Downloads/SLT_AI_EMPLOYEE      # or wherever you unzipped it
bash setup.sh
```

`setup.sh` creates the `.venv` folder and installs the Python packages.

## 2. Start it (every time)

You need **two terminal windows**, both in the `SLT_AI_EMPLOYEE` folder.

**Terminal 1: the model.** Leave it open.

```bash
./start_model.sh
```

The first time, this downloads Gemma 3 4B (about 2.5 GB). Wait until it says the server is listening.

**Terminal 2: the app.**

```bash
./start_app.sh
```

Open **http://localhost:8000** in your browser. To stop, press Control+C in each terminal.

Optional check that the model answers in JSON:

```bash
.venv/bin/python run.py check
```

If `./start_model.sh` says "permission denied", run `bash start_model.sh` (and `bash start_app.sh`) instead.

## 3. A five-minute demo

1. You start as the **HR Officer** (top right). Go to **Add CV** and press **Load the sample CVs** (seven made-up students in PDF, Word and text files).
2. Watch the **Dashboard**: the Recruiter reads the CVs and the Coordinator drafts invitations. A local 4B model makes several calls per CV, so this can take a minute or more per CV. The exact speed is only known when you run it.
3. Open the **Review queue**:
   - **Ishara** has a borderline score (50 to 59). Decide Shortlist or Not shortlisted.
   - **Tharushi** has an HR CV. The AI suggests a new area, "Human Resources", instead of forcing her into an IT area. Add the area on the **Areas** page (give it required skills), then choose it on her candidate page.
   - **Nimal** has a weak CV. Choose an area, then confirm Not shortlisted.
4. Open **Replies** and release an interview invitation. It is saved to `data/outbox/`, not sent.
5. Switch the role to **Interviewer** (top right). Open **Interviews**, pick the student, and enter **Pass** with a comment.
6. Switch back to **HR Officer**. The Onboarding employee issues work ID **1001** and drafts the acceptance email. Release it to close the application.
7. On the Dashboard press **Write brief now** to see the Chief of staff's morning brief. The **AI team** page shows every employee, its routines, what it has learned, and every step it took.

## 4. How it works

```
HR officer adds CV
   -> Recruiter:    read CV -> duplicate check -> choose area -> score -> skill gaps -> shortlist rule
        60+ Shortlisted | 50-59 HR officer decides | below 50 HR officer confirms | unsure area -> HR officer
   -> Coordinator:  interview slot -> questions -> invitation draft  -> HR officer releases
   -> Interviewer:  Pass / Fail / Hold
   -> Pass: Onboarding: work ID -> acceptance draft -> checklist     -> HR officer releases -> Closed
      Fail: Coordinator: rejection draft                             -> HR officer releases -> Closed
      Hold: Coordinator: hold note -> HR officer releases -> On hold -> Interviewer enters Pass or Fail later
```

- **The status of a candidate is the hand-off.** Each employee runs on its own schedule and picks up the candidates in its trigger status. The employees never call each other.
- **Each employee is a folder of Markdown files** in `employees/`, following the "AI employees" repo idea:
  `ROLE.md` (who it is, goes into every prompt), `SCHEDULE.md` (when it runs), `RELEASES.md` (what it may do without a person) and `routines/<name>/SKILL.md` (one routine each). The **Instructions for the model** and **Output** sections of a SKILL file are the prompt. Edit them to change the behaviour without touching code.
- **Each employee's work is a LangGraph graph** (`hiring/flows.py`). The scheduler is APScheduler (`hiring/scheduler.py`).
- **The model proposes, plain code decides** (`hiring/checks.py`):
  - every profile item, name, email and evidence phrase must really be written in the CV;
  - emails must contain the right name, area, date and ID, with no invented numbers and no placeholders like `[Name]`;
  - a failed check goes back to the model with the problems (up to 2 fixes); after that the employee uses plain rules or a template and marks the candidate for the HR officer;
  - the **score is calculated by code** (skills 40, projects 30, education 20, experience 10), never by the model;
  - the **work ID is issued by code**: only after Pass, 4 digits from 1001, never reused, and the same email always gets the same ID.
- **Lessons:** when a check fails, the employee saves a short lesson (no personal data) in `data/notes/` and reads it the next time.
- **The model is never forced into IT areas.** It may suggest a new area. Only a person adds areas.

## 5. Changing things

| To change | Where |
|---|---|
| Areas and their required skills | The **Areas** page |
| Score weights and thresholds (60 / 50) | `hiring/config.py` |
| What an employee is told | `employees/<employee>/ROLE.md` and `routines/<routine>/SKILL.md` |
| How often an employee runs | `employees/<employee>/SCHEDULE.md` (for example `Runs every: 30 seconds`) |
| The model | Stop terminal 1, then run `SLT_MODEL="<huggingface repo>:<quant>" ./start_model.sh`. For example `SLT_MODEL="unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M" ./start_model.sh` (check the exact name on Hugging Face first). |

To start again with an empty system, stop the app and delete the `data` folder.

## 6. Folders

```
SLT_AI_EMPLOYEE/
  setup.sh  start_model.sh  start_app.sh   setup and start
  app.py                                   the web app
  run.py                                   helpers: check, samples, once, brief, status
  employees/                               the 4 AI employees (Markdown)
  shared/areas.json                        starter areas (copied into the register once)
  hiring/
    config.py     settings          db.py        the shared register (SQLite)
    llm.py        llama-server API  checks.py    checks on model answers
    tools.py      CV reading, scoring, slots, templates (plain code)
    employees.py  loads the Markdown folders, checked model steps
    flows.py      LangGraph graphs   scheduler.py  APScheduler
    actions.py    what the two people can do        server.py  FastAPI
  web/                                     the pages (HTML, CSS, JS, Inter font, Lucide icons)
  samples/                                 made-up sample CVs
  tests/                                   tests and the fake model
  data/                                    created when it runs: register.db, inbox, outbox, run-logs, notes
```

## 7. Testing without the real model

```bash
.venv/bin/python -m pytest tests -q
```

These tests use a scripted fake model (`tests/fake_model.py`), so no model is needed. To click through the pages without Gemma, run the fake model as a server in terminal 1 instead of `./start_model.sh`:

```bash
.venv/bin/python tests/fake_model.py --port 8080 --delay 1
```

## 8. Limits (honest)

- **Tested only with the fake model.** How well Gemma 3 4B reads CVs, chooses areas and writes emails, and how long it takes, is only known after you run it. The **AI team** page counts steps that passed, needed a fix, or fell back to rules. Use these numbers to compare models.
- **A wrong area or score can still happen.** The checks prove that the facts are in the CV, not that the decision is right. That is why borderline and low scores always go to the HR officer.
- The evidence check matches words, not meaning. The skills score counts a skill wherever it is mentioned in the CV.
- **Scanned PDFs cannot be read** (there is no OCR). They are marked "CV needs a person".
- No login: the role switch at the top is for the prototype only. Emails are never sent.
- **The area requirements and score weights are our own placeholders.** SLT should confirm them.
- One model call at a time (one local model on an 8 GB Mac).

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| The top bar says "Model not running" | Start `./start_model.sh` in another terminal and wait until it is listening. |
| `llama-server: command not found` | `brew install llama.cpp` |
| `address already in use` on port 8000 or 8080 | Another copy is running. Close it, or start the app with `SLT_APP_PORT=8001 ./start_app.sh`. |
| Very slow | Close other apps. Gemma 3 4B needs about 3 GB of memory. |
| Many "fell back to rules" steps | The model's answers fail the checks. Try another model, or adjust the SKILL instructions. |

Licenses: Inter font (SIL Open Font License, `web/fonts/OFL-Inter.txt`), Lucide icons (ISC, `web/LICENSE-lucide-icons.txt`). All people in `samples/` are made up.
