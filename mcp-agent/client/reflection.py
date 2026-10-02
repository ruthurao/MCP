"""Check a draft against the included facts and rewrite it when it strays."""

from __future__ import annotations

import re
from datetime import date

_NAME = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def reflect(package: dict, proposal: dict) -> tuple[str, dict]:
    reason = proposal.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return "Reflection: confirmed. The draft has no extra claim.", proposal
    names, dates = _allowed(package)
    kept: list[str] = []
    removed: list[str] = []
    for sentence in _sentences(reason):
        if _supported(sentence, names, dates):
            kept.append(sentence)
        else:
            removed.append(sentence)
    if not removed:
        return (
            "Reflection: confirmed. The draft uses only included facts.",
            proposal,
        )
    revised = " ".join(kept).strip() or "The included facts do not support the extra claim."
    updated = {**proposal, "reason": revised}
    return (
        "Reflection: rewritten. Removed a claim that is not in the included facts.\n"
        f"Draft: {revised}"
    ), updated


def _allowed(package: dict) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    dates: set[str] = set()
    policies = []
    equipment = []
    for fact in package["included"]:
        if fact.get("name"):
            names.add(fact["name"])
        if fact["kind"] == "policy":
            policies.append(fact)
        if fact["kind"] == "equipment":
            equipment.append(fact)
        for value in fact.values():
            if isinstance(value, str) and _DATE.fullmatch(value):
                dates.add(value)
    for item in equipment:
        for policy in policies:
            if policy["item"] == item["item"]:
                dates.add(_add_years(item["issued_on"], policy["refresh_years"]))
    return names, dates


def _supported(sentence: str, names: set[str], dates: set[str]) -> bool:
    for name in _NAME.findall(sentence):
        if name not in names:
            return False
    for found in _DATE.findall(sentence):
        if found not in dates:
            return False
    return True


def _sentences(reason: str) -> list[str]:
    parts = re.split(r"(?<=\.)\s+", reason.strip())
    return [part for part in parts if part]


def _add_years(iso_date: str, years: int) -> str:
    year, month, day = (int(part) for part in iso_date.split("-"))
    try:
        return date(year + years, month, day).isoformat()
    except ValueError:
        return date(year + years, month, 28).isoformat()
