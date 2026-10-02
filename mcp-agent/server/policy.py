"""Classify one sentence. Count and age are inputs. The words choose the reason code."""

from __future__ import annotations

import re
from datetime import date

BORDERLINE_DAYS = 180

EXCEPTION_KEYWORDS = ("broken", "stolen", "cracked", "medical", "accessibility")
REPLACEMENT_WORDS = ("replace", "replacement", "refresh", "renew")
ADDITIONAL_WORDS = ("second", "another", "additional", "extra", "new")
NEGATORS = {"not", "no", "isn't", "without"}
ROLES = ("ic", "manager", "executive")

CATALOG = {
    "monitor": "External display for a desk or docking setup.",
    "laptop": "Primary portable computer issued to the employee.",
    "headset": "Headset for calls and meetings.",
    "docking_station": "Dock that connects a laptop to desk peripherals.",
    "keyboard": "Keyboard for the issued computer.",
}

ALIASES = {
    "screen": "monitor",
    "display": "monitor",
    "notebook": "laptop",
    "macbook": "laptop",
    "headphones": "headset",
    "dock": "docking_station",
    "docking station": "docking_station",
}

ELIGIBILITY_REASONS = (
    "within_policy",
    "too_soon",
    "at_cap",
    "borderline_cadence",
    "exception_claimed",
    "unknown_item",
    "multiple_items",
    "unknown_employee",
    "intent_unclear",
    "item_mismatch",
    "role_claim_mismatch",
    "data_error",
    "invalid_input",
    "incomplete_request",
)

ESCALATION_REASONS = (
    "borderline_cadence",
    "exception_claimed",
    "unknown_item",
    "multiple_items",
    "unknown_employee",
    "intent_unclear",
    "item_mismatch",
    "role_claim_mismatch",
    "data_error",
    "invalid_input",
    "incomplete_request",
    "agent_stuck",
    "draft_unverified",
)

_EMPLOYEE_ID = re.compile(r"E\d{4}")
_ROLE_CLAIM = re.compile(
    r"\b(?:i am an?|i'm an?|i’m an?)\s+(ic|manager|executive)\b"
    r"|\bmy role is\s+(?:an?\s+)?(ic|manager|executive)\b",
    re.IGNORECASE,
)


def normalize_employee_id(value: str) -> str | None:
    text = value.strip().upper()
    if _EMPLOYEE_ID.fullmatch(text):
        return text
    return None


def alias_pairs() -> list[tuple[str, str]]:
    mapping = {item: item for item in CATALOG}
    mapping.update(ALIASES)
    ordered = sorted(mapping, key=lambda alias: (-len(alias), alias))
    return [(alias, mapping[alias]) for alias in ordered]


def classify_items(text: str) -> list[str]:
    pairs = alias_pairs()
    if not pairs or not text.strip():
        return []
    lookup = {alias.lower(): canonical for alias, canonical in pairs}
    pattern = "|".join(re.escape(alias) for alias, _canonical in pairs)
    found: list[str] = []
    for match in re.finditer(rf"\b(?:{pattern})\b", text, re.IGNORECASE):
        canonical = lookup[match.group(0).lower()]
        if canonical not in found:
            found.append(canonical)
    return found


def detect_intent(text: str) -> str:
    replacement = bool(
        re.search(r"\b(?:" + "|".join(REPLACEMENT_WORDS) + r")\b", text, re.IGNORECASE)
    )
    additional_words = ADDITIONAL_WORDS
    if replacement:
        additional_words = tuple(word for word in ADDITIONAL_WORDS if word != "new")
    additional = bool(
        re.search(r"\b(?:" + "|".join(additional_words) + r")\b", text, re.IGNORECASE)
    )
    if replacement and additional:
        return "both"
    if replacement:
        return "replacement"
    if additional:
        return "additional"
    return "unspecified"


def surviving_exception_words(text: str) -> list[str]:
    pattern = r"\b(" + "|".join(EXCEPTION_KEYWORDS) + r")\b"
    found: list[str] = []
    for match in re.finditer(pattern, text, re.IGNORECASE):
        before = text[: match.start()]
        tokens = re.findall(r"[A-Za-z]+(?:['’][A-Za-z]+)?", before)
        previous = tokens[-1].lower().replace("’", "'") if tokens else ""
        if previous in NEGATORS:
            continue
        word = match.group(1).lower()
        if word not in found:
            found.append(word)
    return found


def role_claims(text: str) -> list[str]:
    claimed: list[str] = []
    for match in _ROLE_CLAIM.finditer(text):
        role = next(group.lower() for group in match.groups() if group)
        if role not in claimed:
            claimed.append(role)
    return claimed


def add_calendar_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def check_eligibility(
    employee_id: str,
    item: str,
    request_text: str,
    *,
    as_of: date,
    employee: dict | None,
    policy: dict | None,
    conflict: bool,
) -> dict:
    """First matching reason wins. ``policy`` is the included row for the chosen item."""
    eid = normalize_employee_id(employee_id)
    if eid is None:
        return _result(
            "invalid_input",
            None,
            None,
            _evidence(notes="Employee id failed validation."),
        )

    raw_item = (item or "").strip().lower()
    item_arg = None
    if raw_item:
        if raw_item not in CATALOG:
            return _result(
                "invalid_input",
                None,
                None,
                _evidence(employee_id=eid, notes="Item failed validation."),
            )
        item_arg = raw_item

    text = request_text or ""
    if not text.strip() and item_arg is None:
        return _result(
            "incomplete_request",
            None,
            None,
            _evidence(employee_id=eid, notes="No item argument and no request text."),
        )

    if employee is None or employee["employee_id"] != eid:
        return _result(
            "unknown_employee",
            item_arg,
            None,
            _evidence(employee_id=eid, notes="Employee id is not on file."),
        )

    classified = classify_items(text) if text.strip() else []
    if text.strip():
        if len(classified) > 1:
            return _result(
                "multiple_items",
                None,
                None,
                _evidence(
                    employee_id=eid,
                    role=employee["role"],
                    items=classified,
                    notes="The request names more than one catalog item.",
                ),
            )
        if len(classified) == 0:
            return _result(
                "unknown_item",
                None,
                None,
                _evidence(
                    employee_id=eid,
                    role=employee["role"],
                    notes="No catalog item was named in the request text.",
                ),
            )
        chosen = classified[0]
        if item_arg and item_arg != chosen:
            return _result(
                "item_mismatch",
                chosen,
                None,
                _evidence(
                    employee_id=eid,
                    role=employee["role"],
                    items=[item_arg, chosen],
                    notes="Item argument does not match the item classified from the text.",
                ),
            )
    else:
        chosen = item_arg

    if _future_date(employee, as_of):
        return _result(
            "data_error",
            chosen,
            None,
            _evidence(
                employee_id=eid,
                role=employee["role"],
                items=[chosen] if chosen else [],
                notes="A stored hired or issued date is after the as-of date.",
            ),
        )

    claims = role_claims(text)
    contradicted = [claim for claim in claims if claim != employee["role"]]
    if contradicted:
        return _result(
            "role_claim_mismatch",
            chosen,
            None,
            _evidence(
                employee_id=eid,
                role=employee["role"],
                claimed_role=contradicted[0],
                items=[chosen] if chosen else [],
                notes="The sentence asserts a role other than the record.",
            ),
        )

    if conflict and chosen == item_arg:
        return _result(
            "data_error",
            chosen,
            None,
            _evidence(
                employee_id=eid,
                role=employee["role"],
                items=[chosen] if chosen else [],
                notes="Two current rules conflict for this item.",
            ),
        )

    signal = detect_intent(text) if text.strip() else "unspecified"
    held = [unit for unit in employee["equipment"] if unit["item"] == chosen]
    count = len(held)
    if signal == "both" or (signal == "unspecified" and count > 0):
        intent = "both" if signal == "both" else "unspecified"
        return _result(
            "intent_unclear",
            chosen,
            intent,
            _evidence(
                employee_id=eid,
                role=employee["role"],
                items=[chosen],
                count_on_file=count,
                notes="Replacement versus additional intent is not clear.",
            ),
        )

    if policy is None or policy.get("item") != chosen:
        return _result(
            "data_error",
            chosen,
            None,
            _evidence(
                employee_id=eid,
                role=employee["role"],
                items=[chosen] if chosen else [],
                notes="No current policy for this role and item.",
            ),
        )

    max_on_file = policy["max_count"]
    refresh_years = policy["refresh_years"]
    issued_on = None
    due_on = None
    days_until_due = None
    if held:
        oldest = min(held, key=lambda unit: unit["issued_on"])
        issued_on = date.fromisoformat(oldest["issued_on"])
        due_on = add_calendar_years(issued_on, refresh_years)
        days_until_due = (due_on - as_of).days

    if signal == "unspecified":
        resolved_intent = "new"
        mechanical = "within_policy"
        notes = "Unspecified intent with nothing on file is a first issue."
    elif signal == "replacement" and count == 0:
        resolved_intent = "replacement"
        mechanical = "within_policy"
        notes = "Replacement of an item not on file is treated as a first issue."
    elif signal == "additional":
        resolved_intent = "additional"
        if count >= max_on_file:
            mechanical = "at_cap"
            notes = "Already at the role maximum. A due unit does not unlock another."
        else:
            mechanical = "within_policy"
            notes = "Additional unit under the cap. Existing ages do not block it."
    else:
        resolved_intent = "replacement"
        if days_until_due is None:
            mechanical = "within_policy"
            notes = "Replacement of an item not on file is treated as a first issue."
        elif days_until_due <= 0:
            mechanical = "within_policy"
            notes = "Replacement is due today or earlier."
        elif days_until_due <= BORDERLINE_DAYS:
            mechanical = "borderline_cadence"
            notes = "Replacement is due inside the borderline window."
        else:
            mechanical = "too_soon"
            notes = "Replacement is due after the borderline window."

    exceptions = surviving_exception_words(text) if text.strip() else []
    reason = mechanical
    if mechanical in {"too_soon", "at_cap"} and exceptions:
        reason = "exception_claimed"
        notes = "A denial was escalated because an exception word survived."
    elif mechanical == "borderline_cadence" and exceptions:
        notes = "Exception words noted; borderline cadence stands."
    elif mechanical == "within_policy" and exceptions:
        notes = "Exception words do not change an eligible request."

    return _result(
        reason,
        chosen,
        resolved_intent,
        _evidence(
            employee_id=eid,
            role=employee["role"],
            items=[chosen],
            count_on_file=count,
            max_on_file=max_on_file,
            refresh_years=refresh_years,
            issued_on=None if issued_on is None else issued_on.isoformat(),
            due_on=None if due_on is None else due_on.isoformat(),
            days_until_due=days_until_due,
            exception_words=exceptions,
            notes=notes,
        ),
    )


def _future_date(employee: dict, as_of: date) -> bool:
    if date.fromisoformat(employee["start_date"]) > as_of:
        return True
    return any(date.fromisoformat(unit["issued_on"]) > as_of for unit in employee["equipment"])


def _evidence(**overrides: object) -> dict:
    base: dict = {
        "employee_id": None,
        "role": None,
        "claimed_role": None,
        "items": [],
        "count_on_file": None,
        "max_on_file": None,
        "refresh_years": None,
        "issued_on": None,
        "due_on": None,
        "days_until_due": None,
        "exception_words": [],
        "notes": "",
    }
    base.update(overrides)
    return base


def _result(reason_code: str, item: str | None, intent: str | None, evidence: dict) -> dict:
    if reason_code not in ELIGIBILITY_REASONS:
        raise ValueError(f"unknown eligibility reason {reason_code}")
    if reason_code == "within_policy":
        status = "eligible"
    elif reason_code in {"too_soon", "at_cap"}:
        status = "ineligible"
    else:
        status = "ambiguous"
    return {
        "status": status,
        "reason_code": reason_code,
        "item": item,
        "intent": intent,
        "evidence": evidence,
    }
