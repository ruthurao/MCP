# PRD: IT equipment desk

An employee asks for gear in one sentence. The desk freezes that person's record and the current policy, classifies the sentence, then approves a clear yes, denies a clear no, or escalates anything unclear. The agent may use only the facts frozen for that request.

## Users

- An employee, identified by an id, who submits a request.
- A reviewer, who decides escalated requests. This version stores the review. It does not include a review screen.
- An operator, who runs `scripts/ask.py`, `scripts/queue.py`, `scripts/demo.py`, and `scripts/smoke.py`.

## Request

A request has:

| Field | Required | Meaning |
| --- | --- | --- |
| employee_id | yes | `E` plus four digits, such as `E1001`. Any other shape is `invalid_input` |
| item | yes | One catalog id, or free text when the sentence names nothing in the catalog |
| reason | yes | The sentence. It is classified. It is never executed as instructions |
| submitted_on | yes | The as-of date for age, stale policy, and future-date checks. The demo date is 2026-09-30 |

Catalog ids are `laptop`, `monitor`, `keyboard`, `headset`, and `docking_station`.

| Catalog id | Also matches |
| --- | --- |
| monitor | screen, display |
| laptop | notebook, macbook |
| headset | headphones |
| docking_station | dock, docking station |

`computer`, `phone`, and `PC` stay unknown. Two different catalog items in one sentence is `multiple_items`. The handler does not pick one.

## People and policy

Seed these people. `E9999` is not on file.

| Id | Name | Role | Start | Equipment |
| --- | --- | --- | --- | --- |
| E1001 | Priya Shah | ic | 2021-03-01 | Laptop 2021-04-01. Monitor 2024-11-01 |
| E1002 | Jordan Lee | manager | 2019-01-15 | Laptop 2025-02-01. Monitors 2023-01-10 and 2024-06-01 |
| E1003 | Alex Kim | ic | 2024-08-01 | None |
| E1004 | Nora Patel | ic | 2022-05-01 | Monitor 2023-09-30. A replacement is due that day in 2026 |
| E1005 | Chris Adeyemi | ic | 2019-02-01 | Monitor 2024-02-29. A replacement is due 2027-02-28 |
| E1006 | Taylor Brooks | manager | 2018-06-01 | One monitor, 2024-08-01. Count is 1 of 2 |
| E1007 | Mina Cho | ic | 2020-09-01 | Laptop 2022-09-30, due that day in 2026. Keyboard 2025-01-15, due 2028-01-15 |
| E1008 | Owen Garcia | manager | 2017-04-01 | Laptop 2024-01-15, due 2026-01-15. No monitors, so count is 0 of 2 |
| E1009 | Lila Hassan | ic | 2021-11-01 | Headset 2025-03-01, due 2028-03-01. Docking station 2023-09-30, due that day in 2026 |
| E1010 | Riley Chen | executive | 2016-01-04 | Laptop 2025-06-01, due 2027-06-01 |

Tenure on a lookup is the number of days from the start date to `submitted_on`.

Each policy row has `effective_from` and `effective_to`. The seed has one current row per role and item, plus two expired rows: an ic monitor max of 2 that ended 2025-09-30, and an ic laptop max of 2 that ended 2024-12-31. A current row has no `effective_to`, or an `effective_to` on or after the request date.

| Role | Item | Max on file | Refresh |
| --- | --- | --- | --- |
| ic | laptop | 1 | 4 years |
| ic | monitor | 1 | 3 years |
| ic | keyboard, headset, docking_station | 1 each | 3 years |
| manager | laptop | 1 | 2 years |
| manager | monitor | 2 | 3 years |
| manager | keyboard, headset, docking_station | 1 each | 3 years |
| executive | laptop | 1 | 2 years |
| executive | monitor | 2 | 2 years |
| executive | keyboard, headset, docking_station | 1 each | 2 years |

Age uses calendar years. 29 February lands on 28 February when the target year is not a leap year. Replacement age uses the oldest unit of that item.

## Sentence

Intent comes from the reason.

- Replacement words: `replace`, `replacement`, `refresh`, `renew`.
- Additional words: `second`, `another`, `additional`, `extra`, and `new` when no replacement word is present.
- `new` together with a replacement word is a replacement.
- A real additional word together with a replacement word is `intent_unclear`.
- Neither set is `unspecified`. That is a first issue only when the employee holds zero of that item. If they already hold one, unspecified is `intent_unclear`.

Then:

- Additional, and the count is already at the max, is `at_cap`, even when the current unit is due for refresh.
- Additional, under the cap, is `within_policy`. Existing ages do not block it.
- Replacement of something they do not hold is a first issue.
- A replacement due today or earlier is `within_policy`.
- A replacement due in 1 to 180 days inclusive is `borderline_cadence`.
- A replacement due in 181 days or more is `too_soon`.

Exception words: `broken`, `stolen`, `cracked`, `medical`, `accessibility`. Match them on word boundaries. `not`, `no`, `isn't`, and `without` immediately before the word cancel that occurrence.

- `too_soon` or `at_cap` with a surviving exception word becomes `exception_claimed`.
- A request that is already `within_policy` stays eligible.
- `borderline_cadence` stays borderline. The evidence notes the exception words.

`I am a manager`, `I'm an executive`, and `my role is` are claims. A claim that contradicts the record is `role_claim_mismatch`. The record is not upgraded.

First match wins.

1. `invalid_input` when the id is not `E` plus four digits, or the item argument is not a catalog id. `incomplete_request` when there is no item and no text.
2. `unknown_employee` when that id is not the included subject.
3. `multiple_items`, then `unknown_item`, then `item_mismatch` when the item argument and the classified item disagree.
4. `data_error` when a stored start or issue date is after `submitted_on`, or two current rules conflict for the request item.
5. `role_claim_mismatch`.
6. `intent_unclear`.
7. `at_cap`, `too_soon`, `borderline_cadence`, or `within_policy`.
8. If that result is `too_soon` or `at_cap` and an exception word survived, replace it with `exception_claimed`.

## Status

| Reason code | Status |
| --- | --- |
| `within_policy` | eligible |
| `too_soon`, `at_cap` | ineligible |
| every other code below, plus `agent_stuck` and `draft_unverified` | ambiguous |

Ambiguous codes are `borderline_cadence`, `exception_claimed`, `unknown_item`, `multiple_items`, `unknown_employee`, `intent_unclear`, `item_mismatch`, `role_claim_mismatch`, `data_error`, `invalid_input`, `incomplete_request`, `agent_stuck`, and `draft_unverified`.

`eligible` approves. `ineligible` denies. `ambiguous` escalates. The words in the sentence do not get a second vote after the tool returns.

## Context package

Before the agent runs, the service freezes one package for the request.

| Reason code | When | In the hash |
| --- | --- | --- |
| include_subject | The employee on the request | yes |
| include_equipment | Equipment for that employee | yes |
| include_active_policy | The single current row for that role and item | yes |
| exclude_other_employee | Any other employee | no |
| exclude_other_equipment | Equipment owned by someone else | no |
| exclude_stale_policy | `effective_to` is before the request date | no |
| exclude_conflict | Two or more current rows for the same role and item. All of them drop | no |

The hash is SHA-256 of the canonical JSON of included facts. It is written once. The ledger stores memory id and reason code. Another employee's name and equipment stay out of the ledger and out of the prompt. A conflict makes eligibility `ambiguous` with reason `data_error`.

## Tools, resources, and prompts

The agent calls these through MCP, on stdio and on HTTP. Both transports call the same service. Tests call the service directly.

The three lookups are read-only and idempotent. `flag_for_human_review` is idempotent and not read-only. Each tool returns a Pydantic model and logs how long the call took. Completions offer employee ids, catalog items, and roles.

| Tool | Result |
| --- | --- |
| `get_employee_info(employee_id)` | Name, role, start date, tenure in days, and equipment when that id is the included subject. `found: false` when the id is missing or excluded |
| `get_policy_limits(role)` | Max count, refresh years, and memory id for included active rows of that role. `found: false` when the role is not the subject's |
| `check_request_eligibility(employee_id, item, request_text="")` | `status`, `reason_code`, `item`, `intent`, and `evidence`. An empty `request_text` uses the stored reason. The tool does not accept an as-of date |
| `flag_for_human_review(employee_id, request, reason)` | One review line when `reason` is an ambiguous code. An empty reason is rejected. `within_policy`, `too_soon`, and `at_cap` write nothing. A repeat of the same employee, text, and reason returns the same ticket |

The review log is `review_queue.jsonl` beside the database. A ticket id is `RVW-` plus the first 8 hex characters of the SHA-256 of `employee_id|request|reason`.

| Surface | Name | Job |
| --- | --- | --- |
| Resource | `policy://rules` | As-of rules, the 180-day border, and one line per reason code |
| Resource | `policy://catalog` | Catalog ids, descriptions, and aliases |
| Resource | `employee://{employee_id}` | Dossier for the included subject. Anyone else is not on file |
| Resource | `review://queue` | The escalation log. An empty queue says so |
| Prompt | `investigate_request` | How to investigate. Ambiguous means escalate |
| Prompt | `human_review_brief` | Reviewer note. No verdict |
| Prompt | `reflect_on_draft` | Checklist run before a draft is sent |

## Decision

| Status | Decision |
| --- | --- |
| eligible | approve |
| ineligible | deny |
| ambiguous | escalate |

`draft_unverified` and `agent_stuck` escalate even when the tool status was eligible or ineligible.

The reply may state only facts whose ids are in the included set.

## Stop, retry, and a person

The ReAct final answer is a proposal with `decision`, `reason`, and `cited_ids`. `decision` is only `approve`, `deny`, or `escalate`. An escalate also carries `ticket_id` and `reason_code`.

The worker accepts it when all of these hold:

1. Those three fields are present.
2. The reply hash equals the package hash on the request.
3. Every cited id is included.
4. The decision matches the table above.
5. An escalate has a `ticket_id` that is already in the review log.

| Outcome | What the worker does |
| --- | --- |
| Checks pass | Status becomes `approved`, `denied`, or `escalated`. A person is involved only for `escalated` |
| First failure | Status returns to `queued`. Attempt becomes 1. The error is the next observation. The package stays frozen |
| Second failure | Both errors are logged. Status becomes `escalated`. The review reason is `agent_stuck` |

Every stop writes the trace, the package hash, and an audit row. The log does not approve or deny.

Request statuses are `queued`, `running`, `approved`, `denied`, and `escalated`.

## Agent

The model path asks Ollama. The default model is `qwen3:8b` (`EQUIPMENT_MODEL`). Thinking is off and the reply is JSON. The model sees a short summary of each observation. The trace keeps the full text.

`scripts/queue.py --deterministic` does not call the model. It loads `investigate_request`, reads `policy://catalog` and `policy://rules`, calls the tools, and then reflects.

An approve draft that says a replacement will ship within 5 business days fails reflection. The sentence is removed once. If a promise is still all that remains, the request escalates as `draft_unverified` and the draft is not sent. A draft that names a person or a date outside the package is rewritten. A draft that stays inside the package is confirmed.

## Demo requests

`scripts/demo.py` runs these four and prints a Thought, Action, and Observation trace for each.

| Request | Expected |
| --- | --- |
| E1003: I need a laptop for my desk. | approve. `within_policy`. Nothing is on file |
| E1001: I want a bigger second monitor. | deny. `at_cap`. Due date on the oldest monitor is 2027-11-01, and a due unit does not unlock a second one |
| E1002: My laptop was stolen. I need a replacement. | escalate. `borderline_cadence`. Due 2027-02-01, inside the 180-day window. The stolen claim does not change a borderline result |
| E1003: I need a drawing tablet for design work. | escalate. `invalid_input`. Tablet is not a catalog id |

## Chaos score

These run in `tests/server/test_context_chaos.py` on a temporary database. The worker does not inject them. CI is green when all three pass. The score does not approve equipment.

| Seed | Required result |
| --- | --- |
| ic monitor max 2 with `effective_to` last year | `exclude_stale_policy`. The hash keeps max 1 |
| E1002's laptop on a request for E1001 | `exclude_other_employee` and `exclude_other_equipment`. The hash omits Jordan's name and laptop |
| Two current ic laptop limits | `exclude_conflict` on both. Laptop eligibility is `ambiguous` / `data_error` |

## Layout

| Path | Job |
| --- | --- |
| `store/db.py` | Schema, WAL, connection |
| `store/repository.py` | SQL for employees, equipment, policies, requests, context packages, context decisions, and audit log |
| `store/seed.py` | The people and current policy above |
| `server/context.py` | Include, exclude, hash, ledger |
| `server/policy.py` | Aliases, intent, reason codes, and the only eligibility decision |
| `server/reviews.py` | JSONL review log and idempotent ticket ids |
| `server/resources.py` | Catalog, rules, dossier, and the review queue |
| `server/prompts.py` | Investigation, human-review, and reflection text |
| `server/service.py` | Package, four operations, audit |
| `server/mcp.py` | Tools, resources, prompts, and completions on stdio and HTTP |
| `client/intake.py` | Insert a queued request. The stored item is the first catalog id in the sentence |
| `client/worker.py` | Claim, validate, one retry, then escalate |
| `client/agent.py` | ReAct loop. The model sees summaries |
| `client/planner.py` | Scratchpad planner used by `--deterministic` |
| `client/reflection.py` | Confirm a draft, or rewrite a name, a date, or a ship promise |
| `scripts/ask.py` | Submit one sentence |
| `scripts/queue.py` | Start the worker. `--deterministic` skips the model |
| `scripts/demo.py` | The four requests and their traces |
| `scripts/smoke.py` | Stdio proof that calls `get_employee_info` |
| `tests/store/` | Reads and a double claim |
| `tests/server/` | Service, classification, package, chaos |
| `tests/client/` | Reflection, the planner, and the three decisions |
| `.github/workflows/ci.yml` | Unit tests, the chaos score, and ruff |

`store` imports nothing from `server` or `client`. `server` imports `store`. `client` claims rows through `store` and calls tools over MCP.

## Acceptance

- A missing employee id returns `found: false` and the request escalates as `unknown_employee`.
- An id that is not `E` plus four digits is `invalid_input`.
- An empty escalation reason is rejected and no review line is written.
- `within_policy` writes no review line. The same escalation written twice returns the same `RVW-` ticket.
- Two workers cannot claim the same queued row.
- A tool call for another employee returns not-in-package and writes an audit row.
- A draft that says approved when eligibility was ineligible is not saved.
- A draft that promises shipment within 5 business days fails reflection once, then escalates as `draft_unverified` if that promise is all that remains.
- `scripts/smoke.py` prints a real `get_employee_info` response.
- CI runs the unit tests, the three chaos cases, and `ruff check`.

## Out of this version

Auth, a review screen, Postgres, a vector store, and a second queue. Several workers may share one SQLite file. Postgres is a later swap of `store/repository.py`.
