"""Map eligibility and the request reason to approve, deny, or escalate."""

_EXCEPTIONS = (
    "stolen",
    "broken",
    "cracked",
    "accessibility",
    "medical",
    "accommodation",
    "role change",
)


def has_exception(reason: str) -> bool:
    text = reason.lower()
    return any(word in text for word in _EXCEPTIONS)


def expected_decision(eligibility: str, reason: str) -> str:
    if eligibility == "eligible":
        return "approve"
    if eligibility == "ineligible" and not has_exception(reason):
        return "deny"
    return "escalate"
