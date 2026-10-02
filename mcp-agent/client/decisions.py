"""Map a tool status to approve, deny, or escalate."""

_OVERRIDE = {"draft_unverified", "agent_stuck"}


def expected_decision(eligibility: str, reason_code: str = "") -> str:
    if reason_code in _OVERRIDE:
        return "escalate"
    if eligibility == "eligible":
        return "approve"
    if eligibility == "ineligible":
        return "deny"
    return "escalate"
