"""Instruction text. The prompts do not decide eligibility."""

from __future__ import annotations

import re

_UNVERIFIED_PROMISE = re.compile(
    r"ship(?:s|ped|ping)?\s+within\s+\d+\s+business\s+days"
    r"|\$\s*\d"
    r"|\bmodel\s+[A-Za-z0-9-]+\b"
    r"|\b(?:cost|price)\s+of\s+\$?\d",
    re.IGNORECASE,
)

UNVERIFIED_SHIP_SENTENCE = "A replacement will ship within 5 business days."


def draft_has_unverified_promise(draft: str) -> bool:
    return _UNVERIFIED_PROMISE.search(draft) is not None


def investigate_request(employee_id: str, request_text: str) -> str:
    """How to investigate one request. Ambiguous means escalate."""
    return (
        f"Investigate the equipment request for employee {employee_id}.\n"
        "\n"
        "Request text:\n"
        f"{request_text}\n"
        "\n"
        "Before classifying an item, read resource policy://catalog.\n"
        "Next tool: get_employee_info.\n"
        "Use the role from that tool, not from the sentence.\n"
        "If the eligibility status is ambiguous, escalate. Do not guess a verdict.\n"
    )


def human_review_brief(employee_id: str, request_text: str, reason_code: str) -> str:
    """Reviewer note for an escalation. States no verdict."""
    return (
        f"Human review brief for employee {employee_id}.\n"
        f"Request: {request_text}\n"
        f"Reason code: {reason_code}\n"
        "No verdict. Do not approve or deny this request. A human reviewer decides.\n"
        "Pass this reason code to flag_for_human_review.\n"
    )


def reflect_on_draft(draft: str) -> str:
    """Checklist run before a draft is sent."""
    return (
        "Review this draft before it is sent.\n"
        "\n"
        "Draft:\n"
        f"{draft}\n"
        "\n"
        "Checklist:\n"
        "- Every date, role, cadence, and reason code in the draft appears in a tool "
        "observation or a resource body.\n"
        "- Approve is used only when the tool status is eligible.\n"
        "- Deny is used only when the tool status is ineligible.\n"
        "- Escalate requires a confirmed review ticket in the draft and on the queue.\n"
        "- Reject a draft that says a replacement will ship within 5 business days.\n"
    )
