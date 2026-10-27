"""A scripted stand-in for the real model, used by the tests (no Ollama or llama.cpp needed).

It reads the routine name and the data blocks from the prompt and answers like a
well-behaved model. `FakeModel.bad` makes it give wrong answers first, so the
checks, fixes and fallbacks can be tested.

Run it as a server (same API as llama-server) for trying the web pages without a model:
    python tests/fake_model.py --port 8080
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiring import tools  # noqa: E402
from hiring.checks import CVText  # noqa: E402


def _block_json(text: str, label: str):
    i = text.find(f"{label} (JSON):")
    if i < 0:
        return None
    j = text.find("\n", i) + 1
    obj, _ = json.JSONDecoder().raw_decode(text[j:].lstrip())
    return obj


def _cv(text: str) -> str:
    m = re.search(r"CV TEXT:\n<<<\n(.*?)\n>>>", text, flags=re.S)
    return m.group(1) if m else ""


def _vocab() -> list[str]:
    areas = json.loads((ROOT / "shared" / "areas.json").read_text(encoding="utf-8"))
    v = list(tools.GENERAL_SKILLS)
    for a in areas:
        v += a["required_skills"] + a["preferred_skills"]
    return list(dict.fromkeys(v))


class FakeModel:
    def __init__(self, delay: float = 0.0):
        self.bad: dict[str, int] = {}     # routine -> number of bad answers to give first
        self.calls: list[str] = []
        self.delay = delay

    def __call__(self, messages: list, json_mode: bool = True) -> str:
        text = "\n\n".join(m["content"] for m in messages)
        first = "\n\n".join(m["content"] for m in messages[:2])
        m = re.search(r"ROUTINE: ([a-z\-]+)", text)
        routine = m.group(1) if m else ""
        self.calls.append(routine)
        if self.delay:
            time.sleep(self.delay)
        if self.bad.get(routine, 0) > 0:
            self.bad[routine] -= 1
            return self.bad_answer(routine)
        return json.dumps(self.good_answer(routine, first))

    # ---- good answers ----
    def good_answer(self, routine: str, text: str) -> dict:
        if routine == "parse-cv":
            return tools.rule_profile(_cv(text), _vocab())
        if routine == "choose-area":
            cv_text = _cv(text)
            cv = CVText(cv_text)
            best, best_found, best_share = None, [], 0.0
            for a in _block_json(text, "AREAS") or []:
                req = a.get("required_skills") or []
                found = [s for s in req if cv.has(s)]
                share = len(found) / len(req) if req else 0
                if share > best_share:
                    best, best_found, best_share = a["name"], found, share
            if best and best_share >= 0.34:
                return {"area": best, "reasons": [f"The CV shows {len(best_found)} of the main {best} skills."],
                        "evidence": best_found[:3]}
            if cv.has("recruitment") or cv.has("human resources"):
                return {"area": "New area: Human Resources", "reasons": ["The CV is about HR work."],
                        "evidence": ["recruitment"]}
            return {"area": "Needs human review", "reasons": ["The CV does not fit any area."], "evidence": []}
        if routine == "prepare-questions":
            f = _block_json(text, "FACTS") or {}
            qs = [f"Why do you want to work in {f.get('area')}?",
                  "Which project in your CV are you most proud of, and why?",
                  "What was the hardest bug you fixed, and how did you find it?"]
            for g in (f.get("skill_gaps") or [])[:2]:
                qs.append(f"What do you know about {g} so far?")
            while len(qs) < 5:
                qs.append("How do you plan your work when you have several deadlines?")
            return {"questions": qs}
        if routine == "morning-brief":
            f = _block_json(text, "FACTS") or {}
            n = f.get("needs_a_person_today", {})
            total = f.get("total_items_needing_a_person", 0)
            return {"brief": (f"Good morning. Today {total} item(s) need your attention, including "
                              f"{n.get('emails_waiting_for_release', 0)} email(s) waiting for release. "
                              f"{f.get('waiting_for_interview_results', 0)} candidate(s) are waiting for an "
                              f"interview result. The AI employees read {f.get('last_24_hours', {}).get('cvs_read', 0)} "
                              f"CV(s) in the last 24 hours. Please check the Review queue first.")}
        if routine == "ask-cv":
            cv_text = _cv(text)
            m = re.search(r"QUESTION:\n(.*?)\n\nCV TEXT:", text, flags=re.S)
            question = m.group(1).strip() if m else ""
            prof = tools.rule_profile(cv_text, _vocab())
            return tools.rule_answer_cv(question, cv_text, prof)
        # drafts
        f = _block_json(text, "FACTS") or {}
        first = f.get("first_name", "there")
        area = f.get("area", "")
        sign = "\n\nKind regards,\nSLT Internship Team"
        if routine == "invite-and-slots":
            return {"subject": f"Invitation to interview for the {area} internship",
                    "body": (f"Dear {first},\n\nThank you for your application ({f.get('app_no')}). We would like to "
                             f"invite you to an interview for the {area} internship on {f.get('interview')}. "
                             f"Please reply to confirm that you can attend.{sign}")}
        if routine == "draft-acceptance":
            return {"subject": f"Welcome to the {area} internship at SLT",
                    "body": (f"Dear {first},\n\nCongratulations! You have been selected for the {area} internship. "
                             f"Your work ID is {f.get('work_id')}. Please use it in all your messages with us. "
                             f"Our team will contact you soon with the induction details.{sign}")}
        if routine == "reply-failed-or-hold" and f.get("message_type") == "hold":
            return {"subject": "Your interview result",
                    "body": (f"Dear {first},\n\nThank you for attending the interview. Your result is on hold for "
                             f"now, and we will contact you when a decision has been made. Thank you for your "
                             f"patience.{sign}")}
        return {"subject": "Your internship application",
                "body": (f"Dear {first},\n\nThank you for your interest in an internship at SLT. After careful "
                         f"review we are not able to take your application further this time. We wish you the "
                         f"very best with your studies.{sign}")}

    # ---- bad answers (to test checks and fixes) ----
    def bad_answer(self, routine: str) -> str:
        if routine == "parse-cv":
            return json.dumps({"name": "John Invented", "email": "fake@nowhere.com", "phone": "",
                               "education": ["PhD at MIT"], "skills": ["Kubernetes", "Rust", "Go", "Scala"],
                               "projects": ["Built a rocket"], "experience": ["CEO of Google"]})
        if routine == "choose-area":
            return json.dumps({"area": "DevOps", "reasons": ["Seems good."], "evidence": ["Kubernetes expert at Google"]})
        if routine == "prepare-questions":
            return json.dumps({"questions": ["Tell me about yourself"]})
        if routine == "morning-brief":
            return json.dumps({"brief": "Good morning. 999 students applied today and 42 need you now. "
                                        "Everything else is fine and the team did a great job overall today."})
        if routine == "ask-cv":
            return json.dumps({"answer": "The candidate worked for 10 years at NASA.",
                               "quotes": ["10 years as Principal Engineer at NASA"]})
        if routine == "parse-not-json":
            return "Sure! Here is the profile."
        return json.dumps({"subject": "Hello", "body": "Dear [Name], please come within 14 days. "
                                                       "We look forward to it very much and hope you can join us soon. "
                                                       "Thank you for your time and interest in our programme."})


# ---- run as a server -------------------------------------------------------------------
def serve(port: int, delay: float = 0.0) -> None:
    model = FakeModel(delay=delay)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, obj: dict) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self._send(200, {"status": "ok"})
            elif self.path == "/v1/models":
                self._send(200, {"data": [{"id": "fake-gemma-3-4b"}]})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self._send(404, {"error": "not found"})
                return
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(n) or b"{}")
            text = model(req.get("messages", []), True)
            self._send(200, {"choices": [{"message": {"role": "assistant", "content": text}}]})

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--delay", type=float, default=0.0, help="seconds to wait before each answer")
    a = ap.parse_args()
    print(f"Fake model listening on http://127.0.0.1:{a.port}")
    serve(a.port, a.delay)
