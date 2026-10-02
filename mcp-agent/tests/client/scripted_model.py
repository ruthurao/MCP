"""A model double that reads the scratchpad and names the next tool."""

import json

from client.decisions import expected_decision


def scripted_model(catalog: list[dict], scratchpad: str, request: dict) -> str:
    names = {tool["name"] for tool in catalog}
    if names != {
        "get_employee_info",
        "get_policy_limits",
        "check_request_eligibility",
        "flag_for_human_review",
    }:
        raise AssertionError(names)
    if "Action: get_employee_info" not in scratchpad:
        return _call(
            "Look up the employee on this request.",
            "get_employee_info",
            {"employee_id": request["employee_id"]},
        )
    info = _observation_after(scratchpad, "get_employee_info")
    if info.get("found") and "Action: get_policy_limits" not in scratchpad:
        return _call(
            "Read the policy for this role.",
            "get_policy_limits",
            {"role": info["role"]},
        )
    if "Action: check_request_eligibility" not in scratchpad:
        return _call(
            "Check eligibility against the package.",
            "check_request_eligibility",
            {
                "employee_id": request["employee_id"],
                "item": request["item"],
                "request_text": request["reason"],
            },
        )
    eligibility = _observation_after(scratchpad, "check_request_eligibility")
    decision = expected_decision(eligibility["status"], eligibility.get("reason_code") or "")
    if decision == "escalate" and "Action: flag_for_human_review" not in scratchpad:
        return _call(
            "A person should review this request.",
            "flag_for_human_review",
            {
                "employee_id": request["employee_id"],
                "request": request["reason"],
                "reason": eligibility["reason_code"],
            },
        )
    cited: list[str] = []
    if info.get("found"):
        cited.append(f"employee:{request['employee_id']}")
    limits = _observation_after(scratchpad, "get_policy_limits") if info.get("found") else {}
    memory_id = (limits.get("limits") or {}).get(request["item"], {}).get("memory_id")
    if memory_id:
        cited.append(memory_id)
    notes = (eligibility.get("evidence") or {}).get("notes") or eligibility.get("reason_code")
    proposal = {
        "decision": decision,
        "reason": notes,
        "reason_code": eligibility.get("reason_code") or "",
        "cited_ids": cited,
    }
    if decision == "escalate":
        review = _observation_after(scratchpad, "flag_for_human_review")
        proposal["ticket_id"] = review["ticket_id"]
    return json.dumps({"thought": "The package is enough to answer.", "proposal": proposal})


def _call(thought: str, action: str, arguments: dict) -> str:
    return json.dumps({"thought": thought, "action": action, "arguments": arguments})


def _observation_after(scratchpad: str, tool: str) -> dict:
    lines = scratchpad.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(f"Action: {tool} " ) or line == f"Action: {tool}":
            for later in lines[index + 1 :]:
                if later.startswith("Observation: "):
                    return json.loads(later.removeprefix("Observation: "))
    raise AssertionError(tool)
