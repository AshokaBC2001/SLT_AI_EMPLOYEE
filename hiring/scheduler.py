"""Runs each AI employee on the schedule written in its SCHEDULE.md (APScheduler)."""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import flows
from .employees import EMPLOYEES, schedule

_scheduler: BackgroundScheduler | None = None


def start() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    s = BackgroundScheduler(job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60})
    for key in EMPLOYEES:
        plan = schedule(key)
        if key == "chief-of-staff":
            if plan["daily_at"]:
                h, m = plan["daily_at"].split(":")
                s.add_job(flows.run_chief, CronTrigger(hour=int(h), minute=int(m)), kwargs={"wait": True},
                          id=key, name=EMPLOYEES[key])
            continue
        if plan["every_seconds"]:
            s.add_job(flows.run_employee, IntervalTrigger(seconds=plan["every_seconds"]), args=[key],
                      id=key, name=EMPLOYEES[key])
        elif plan["daily_at"]:
            h, m = plan["daily_at"].split(":")
            s.add_job(flows.run_employee, CronTrigger(hour=int(h), minute=int(m)), args=[key],
                      id=key, name=EMPLOYEES[key])
    s.start()
    _scheduler = s
    return s


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def next_runs() -> dict[str, str]:
    if _scheduler is None:
        return {}
    out = {}
    for job in _scheduler.get_jobs():
        if job.next_run_time:
            out[job.id] = job.next_run_time.replace(microsecond=0, tzinfo=None).isoformat()
    return out
