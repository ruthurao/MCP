"""Read-only documents rendered from the package and the catalog."""

from __future__ import annotations

import sqlite3

from server.policy import ALIASES, BORDERLINE_DAYS, CATALOG, ELIGIBILITY_REASONS, ESCALATION_REASONS
from server.reviews import log_path, read_entries
from server.service import get_employee_info

_REASON_LINES = {
    "within_policy": "First issue, additional unit under the cap, or a replacement that is due.",
    "too_soon": "Replacement due in 181 days or more, with no surviving exception word.",
    "at_cap": "Additional unit when the employee is already at the role maximum.",
    "borderline_cadence": (
        f"A replacement due in 1 to {BORDERLINE_DAYS} days inclusive is borderline."
    ),
    "exception_claimed": "A denial plus a surviving exception word. Escalate. Do not approve.",
    "unknown_item": "No catalog item was named in the request text.",
    "multiple_items": "The request names more than one catalog item.",
    "unknown_employee": "Employee id is not on file.",
    "intent_unclear": "Replacement versus additional intent is not clear.",
    "item_mismatch": "Item argument does not match the item classified from the text.",
    "role_claim_mismatch": "The sentence asserts a role other than the record.",
    "data_error": "A stored date is after the as-of date, or two current rules conflict.",
    "invalid_input": "Employee id or item failed validation.",
    "incomplete_request": "No item argument and no request text.",
    "agent_stuck": "The investigation stopped before a draft.",
    "draft_unverified": "The draft still failed reflection after one revision.",
}


def read_catalog() -> str:
    lines = ["Catalog", ""]
    for item in sorted(CATALOG):
        aliases = [alias for alias, canonical in ALIASES.items() if canonical == item]
        aliases.append(item)
        aliases = sorted(set(aliases), key=lambda alias: (-len(alias), alias))
        lines.append(f"Item: {item}")
        lines.append(CATALOG[item])
        lines.append("Aliases: " + ", ".join(aliases))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def read_policy_rules() -> str:
    lines = [
        "Policy rules",
        "",
        f"A replacement due in 1 to {BORDERLINE_DAYS} days inclusive is borderline "
        "and escalates. A replacement due in 181 days or more is too soon.",
        "Exception words are matched on word boundaries. not, no, isn't, and without "
        "immediately before the word cancel that occurrence.",
        "An additional unit at the cap is at_cap even when the current unit is due.",
        "Replacement age uses the oldest unit of that item.",
        "",
    ]
    for code in (*ELIGIBILITY_REASONS, "agent_stuck", "draft_unverified"):
        if code in ESCALATION_REASONS or code in ELIGIBILITY_REASONS:
            lines.append(f"{code}: {_REASON_LINES[code]}")
    return "\n".join(lines) + "\n"


def read_employee_dossier(connection: sqlite3.Connection, request_id: int, employee_id: str) -> str:
    info = get_employee_info(connection, request_id, employee_id)
    if not info["found"]:
        return f"Employee {employee_id} is not on file.\n"
    lines = [
        f"# {info['name']} ({info['employee_id']})",
        f"Role: {info['role']}",
        f"Hired: {info['start_date']}",
        f"Tenure: {info['tenure_days']} days",
        "",
    ]
    if info["equipment"]:
        for unit in info["equipment"]:
            lines.append(f"- {unit['item']} issued {unit['issued_on']}")
    else:
        lines.append("No equipment on file.")
    return "\n".join(lines) + "\n"


def read_review_queue(connection: sqlite3.Connection) -> str:
    entries, corrupt = read_entries(log_path(connection))
    if not entries and not corrupt:
        return "The review queue is empty.\n"
    lines = ["Review queue", ""]
    for entry in entries:
        lines.append(
            f"{entry['ticket_id']} {entry['employee_id']} {entry['reason']}: {entry['request']}"
        )
    if corrupt:
        lines.append(f"Corrupt lines: {', '.join(str(number) for number in corrupt)}")
    return "\n".join(lines) + "\n"
