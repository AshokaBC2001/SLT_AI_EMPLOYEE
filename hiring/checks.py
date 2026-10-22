"""Plain-code checks on everything the model writes.

The model proposes, these checks decide. A failed check sends the problems
back to the model for a fix; after the allowed fixes the employee falls back
to plain rules or a template and marks the result for a person to look at.
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import config

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
STOP = {"a", "an", "the", "and", "or", "of", "in", "on", "for", "to", "with", "at", "by", "from", "as",
        "is", "was", "were", "using", "use", "used", "my", "i", "their", "this", "that", "be", "have",
        "has", "it", "its", "into", "via", "also", "etc"}
PLACEHOLDER_RE = re.compile(r"\[[^\]]{0,40}\]|\{[^}]{0,40}\}|<[^>]{1,40}>|\bX{2,}\b|lorem ipsum|your name here|insert ", re.I)


# ---- JSON ----------------------------------------------------------------------------
def parse_json_object(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I).strip()
    try:
        obj = json.loads(t)
    except ValueError:
        start, end = t.find("{"), t.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("The answer was not JSON.")
        obj = json.loads(t[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("The answer was not a JSON object.")
    return obj


# ---- "is this really written in the CV?" ----------------------------------------
def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+#]+", " ", (s or "").lower()).strip()


class CVText:
    """The CV text prepared once for fast phrase checks."""

    def __init__(self, text: str):
        self.raw = text or ""
        self.norm = " " + norm(self.raw) + " "
        self.tokens = set(self.norm.split())
        self.digits = re.sub(r"\D", "", self.raw)

    def has(self, phrase: str) -> bool:
        p = norm(phrase)
        if not p:
            return False
        if f" {p} " in self.norm:
            return True
        words = [w for w in p.split() if w not in STOP]
        if not words:
            return False
        found = 0
        for w in words:
            if w in self.tokens or w + "s" in self.tokens or (w.endswith("s") and w[:-1] in self.tokens):
                found += 1
            elif len(w) > 4 and any(t.startswith(w[:5]) for t in self.tokens):
                found += 1   # "deployed" and "deployment" share a stem
        if len(words) <= 3:
            return found == len(words)
        return found / len(words) >= 0.8


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, dict):
            item = " - ".join(str(v) for v in item.values() if v)
        item = str(item).strip()
        if item and item not in out:
            out.append(item)
    return out


# ---- CV profile ------------------------------------------------------------------------
PROFILE_LISTS = ("education", "skills", "projects", "experience")


def check_profile(data: Any, cv_text: str) -> tuple[dict, list[str], list[str]]:
    """Returns (clean profile, problems, removed items)."""
    problems: list[str] = []
    if not isinstance(data, dict):
        return {}, ["The answer was not a JSON object."], []
    cv = CVText(cv_text)
    name = str(data.get("name") or "").strip()
    if not name:
        problems.append("The name is missing.")
    elif not cv.has(name):
        problems.append(f'The name "{name}" is not written in the CV.')
    email = str(data.get("email") or "").strip()
    if email:
        if not EMAIL_RE.fullmatch(email):
            problems.append(f'"{email}" is not a valid email address.')
        elif email.lower() not in cv.raw.lower():
            problems.append(f'The email "{email}" is not written in the CV.')
    phone = str(data.get("phone") or "").strip()
    if phone and re.sub(r"\D", "", phone) not in cv.digits:
        problems.append(f'The phone number "{phone}" is not written in the CV.')
    clean = {"name": name, "email": email, "phone": phone}
    removed: list[str] = []
    total = 0
    for key in PROFILE_LISTS:
        kept = []
        for item in _as_list(data.get(key)):
            total += 1
            if cv.has(item):
                kept.append(item[:300])
            else:
                removed.append(item)
        clean[key] = kept[:20]
    if total and len(removed) > max(2, total * 0.4):
        sample = "; ".join(removed[:3])
        problems.append(f"{len(removed)} items are not written in the CV (for example: {sample}). "
                        "Only copy what the CV says.")
    return clean, problems, removed


# ---- Area choice ------------------------------------------------------------------------
ALIASES = {
    "ai": "AI/ML", "ml": "AI/ML", "ai ml": "AI/ML", "machine learning": "AI/ML",
    "artificial intelligence": "AI/ML", "data science": "AI/ML", "ai and ml": "AI/ML",
    "dev ops": "DevOps", "devops": "DevOps", "ml ops": "MLOps", "mlops": "MLOps",
    "flutter": "Flutter", "mobile": "Flutter", "mobile development": "Flutter",
    "mobile app development": "Flutter",
}


def resolve_area(raw: str, area_names: list[str]) -> str | None:
    r = norm(raw)
    if not r:
        return None
    for name in area_names:
        if norm(name) == r or norm(name).replace(" ", "") == r.replace(" ", ""):
            return name
    alias = ALIASES.get(r)
    if alias and alias in area_names:
        return alias
    return None


def clean_area_name(raw: str) -> str:
    s = re.sub(r"[^A-Za-z0-9 &/\-]", "", raw or "").strip()
    s = re.sub(r"\s+", " ", s)[:40]
    return s.title() if s.islower() else s


def check_area(data: Any, area_names: list[str], cv_text: str) -> tuple[dict, list[str]]:
    if not isinstance(data, dict):
        return {}, ["The answer was not a JSON object."]
    problems: list[str] = []
    raw = str(data.get("area") or "").strip()
    reasons = [r[:250] for r in _as_list(data.get("reasons"))][:3]
    evidence = _as_list(data.get("evidence"))
    resolved = resolve_area(raw, area_names)
    new_area = ""
    if resolved is None:
        low = raw.lower()
        if low in ("", "none", "unknown", config.NEEDS_REVIEW_AREA.lower()):
            resolved = config.NEEDS_REVIEW_AREA
        else:
            name = raw.split(":", 1)[1] if low.startswith("new area") and ":" in raw else raw
            new_area = clean_area_name(name)
            if not new_area:
                problems.append("The area name is empty.")
    if not reasons:
        problems.append("Give 1 to 3 short reasons.")
    cv = CVText(cv_text)
    good_evidence = [e[:200] for e in evidence if cv.has(e)]
    if resolved != config.NEEDS_REVIEW_AREA and not good_evidence:
        problems.append("None of the evidence phrases are written in the CV. Quote 1 to 4 short phrases "
                        "copied exactly from the CV.")
    return {"area": resolved or "", "new_area": new_area, "reasons": reasons,
            "evidence": good_evidence[:4]}, problems


# ---- Drafted replies ---------------------------------------------------------------------
def _numbers_in(value: Any) -> set[str]:
    if isinstance(value, dict):
        out: set[str] = set()
        for v in value.values():
            out |= _numbers_in(v)
        return out
    if isinstance(value, (list, tuple, set)):
        out = set()
        for v in value:
            out |= _numbers_in(v)
        return out
    return {n.lstrip("0") or "0" for n in re.findall(r"\d+", str(value))}


def check_draft(data: Any, facts: dict, must_include: list[str], must_not_include: list[str] | None = None
                ) -> tuple[dict, list[str]]:
    if not isinstance(data, dict):
        return {}, ["The answer was not a JSON object."]
    subject = str(data.get("subject") or "").strip()[:200]
    body = str(data.get("body") or "").strip()
    problems: list[str] = []
    if not subject:
        problems.append("The subject is missing.")
    words = len(body.split())
    if words < 25:
        problems.append("The email body is too short.")
    if words > 260:
        problems.append("The email body is too long. Keep it under 200 words.")
    text = f"{subject}\n{body}"
    low = text.lower()
    first_name = (facts.get("name") or "").split()[0] if facts.get("name") else ""
    if first_name and first_name.lower() not in low:
        problems.append(f'The email must greet the student by name ("{first_name}").')
    for item in must_include:
        if item and str(item).lower() not in low:
            problems.append(f'The email must include "{item}" exactly as given.')
    for item in must_not_include or []:
        if item.lower() in low:
            problems.append(f'The email must not say "{item}".')
    allowed = _numbers_in(facts)
    extra = sorted({n.lstrip("0") or "0" for n in re.findall(r"\d+", text)} - allowed)
    if extra:
        problems.append("The email has numbers that are not in the facts: " + ", ".join(extra[:6]) +
                        ". Do not add dates, times or numbers of your own.")
    if PLACEHOLDER_RE.search(text):
        problems.append("The email has a placeholder such as [Name]. Write the real text from the facts.")
    return {"subject": subject, "body": body}, problems


# ---- Interview questions --------------------------------------------------------------
def check_questions(data: Any) -> tuple[list[str], list[str]]:
    if not isinstance(data, dict):
        return [], ["The answer was not a JSON object."]
    qs = []
    for q in _as_list(data.get("questions")):
        q = re.sub(r"^\s*\d+[.)]\s*", "", q).strip()
        if q and q not in qs:
            qs.append(q[:300])
    problems = []
    if not 4 <= len(qs) <= 8:
        problems.append(f"Write 4 to 8 questions (you wrote {len(qs)}).")
    bad = [q for q in qs if not q.endswith("?") or len(q) < 15]
    if bad:
        problems.append("Every question must be a full sentence that ends with a question mark.")
    return qs[:8], problems


# ---- Morning brief --------------------------------------------------------------------
def check_brief(data: Any, facts: dict) -> tuple[str, list[str]]:
    if not isinstance(data, dict):
        return "", ["The answer was not a JSON object."]
    text = str(data.get("brief") or "").strip()
    problems = []
    words = len(text.split())
    if words < 25:
        problems.append("The brief is too short.")
    if words > 220:
        problems.append("The brief is too long. Keep it under 180 words.")
    allowed = _numbers_in(facts) | {"24"}     # "the last 24 hours" is always allowed
    extra = sorted({n.lstrip("0") or "0" for n in re.findall(r"\d+", text)} - allowed)
    if extra:
        problems.append("The brief has numbers that are not in the facts: " + ", ".join(extra[:6]) + ".")
    return text, problems
