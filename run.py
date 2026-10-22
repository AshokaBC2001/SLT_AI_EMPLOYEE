"""Command line helpers.

    .venv/bin/python run.py check        is the model server running, and does it answer in JSON?
    .venv/bin/python run.py samples      add the sample CVs
    .venv/bin/python run.py once         let the Recruiter, Coordinator and Onboarding work once
    .venv/bin/python run.py brief        let the Chief of staff write the morning brief
    .venv/bin/python run.py status       list the candidates and their status
"""
import argparse
import json
import sys
import time

from hiring import config, db, flows, llm, actions
from hiring.checks import parse_json_object


def check() -> int:
    h = llm.health(force=True)
    print(f"Model server {config.MODEL_URL}: {h['detail']}")
    if not h["ok"]:
        return 1
    print(f"Model: {h['model']}. Asking a test question...")
    t = time.time()
    try:
        text = llm.chat([{"role": "user", "content": 'Reply with this JSON object only: {"ready": true, "colour": "green"}'}],
                        json_mode=True, max_tokens=50)
    except llm.ModelUnavailable as e:
        print("Failed:", e)
        return 1
    print(f"Answer in {time.time() - t:.1f} s: {text.strip()[:200]}")
    try:
        parse_json_object(text)
        print("OK: the model answers in JSON. You can start the app.")
        return 0
    except ValueError:
        print("The answer was not JSON. The app will still work, but expect more fixes and fallbacks.")
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="SLT AI Employee helpers")
    ap.add_argument("command", choices=["check", "samples", "once", "brief", "status"])
    a = ap.parse_args()
    if a.command == "check":
        return check()
    db.setup()
    if a.command == "samples":
        for r in actions.add_samples():
            print(("Added " + r["app_no"]) if r["ok"] else "Skipped", "-", r["file"], "" if r["ok"] else f"({r['reason']})")
    elif a.command == "once":
        for r in flows.run_all_once():
            print(r)
        if flows.NOTICE["text"]:
            print("Stopped:", flows.NOTICE["text"])
    elif a.command == "brief":
        print(flows.run_chief())
        with db.Session() as s:
            from sqlalchemy import select
            b = s.scalar(select(db.Brief).order_by(db.Brief.id.desc()).limit(1))
            if b:
                print("\n" + b.text)
    elif a.command == "status":
        for c in db.candidates_in(set(config.STATUSES)):
            print(f"{c.app_no}  {c.name or '-':28} {config.STATUSES[c.status][0]:32} {c.area or '-':10} "
                  f"{c.score if c.score is not None else '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
