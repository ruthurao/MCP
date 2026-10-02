# PRD: IT equipment desk

An employee asks for gear in one sentence. The desk looks up that person and the policy, then approves a clear yes, denies a clear no, or escalates anything unclear to a person. The agent may use only the facts frozen for that request.

## Users

- An employee, identified by an id, who submits a request.
- A reviewer, who decides escalated requests. This version stores the review. It does not include a review screen.
- An operator, who runs `scripts/ask.py`, `scripts/queue.py`, `scripts/demo.py`, and `scripts/smoke.py`.

## Request

A request has:

| Field | Required | Meaning |
| --- | --- | --- |
| employee_id | yes | Id on file, such as `E1001` |
| item | yes | One catalog item, or free text when the item is unknown |
| reason | yes | Why they want it |
| submitted_on | yes | Date used for policy age and stale rules. The demo date is 2026-09-30 |

Catalog items are `laptop`, `monitor`, `keyboard`, `headset`, and `dock`.

## People and policy

Seed these people. `E9999` is not on file.

| Id | Name | Role | Start | Equipment |
| --- | --- | --- | --- | --- |
| E1001 | Priya Shah | ic | 2021-03-01 | Laptop 2021-04-01. Monitor 2024-11-01 |
| E1002 | Jordan Lee | manager | 2019-01-15 | Laptop 2025-02-01. Monitors 2023-01-10 and 2024-06-01 |
| E1003 | Alex Kim | ic | 2024-08-01 | None |
| E1004 | Nora Patel | ic | 2022-05-01 | Monitor 2023-09-30. On 2026-09-30 the 3-year window opens that day |
| E1005 | Chris Adeyemi | ic | 2019-02-01 | Monitor 2024-02-29. Next eligible 2027-02-28 |
| E1006 | Taylor Brooks | manager | 2018-06-01 | One monitor, 2024-08-01. Count is 1 of 2, so the issue date does not matter |
| E1007 | Mina Cho | ic | 2020-09-01 | Laptop 2022-09-30, eligible that day in 2026. Keyboard 2025-01-15, next eligible 2028-01-15 |
| E1008 | Owen Garcia | manager | 2017-04-01 | Laptop 2024-01-15, 2-year window already open. No monitors, so count is 0 of 2 |
| E1009 | Lila Hassan | ic | 2021-11-01 | Headset 2025-03-01, next eligible 2028-03-01. Dock 2023-09-30, eligible on the request date |

Each policy row has `effective_from` and `effective_to`. The seed has one current row per role and item, plus two expired rows: an ic monitor max of 2 that ended 2025-09-30, and an ic laptop max of 2 that ended 2024-12-31. A current row has no `effective_to`, or an `effective_to` on or after the request date.

| Role | Item | Max on file | Refresh |
| --- | --- | --- | --- |
| ic | laptop | 1 | 4 years |
| ic | monitor | 1 | 3 years |
| ic | keyboard, headset, dock | 1 each | 3 years |
| manager | laptop | 1 | 2 years |
| manager | monitor | 2 | 3 years |
| manager | keyboard, headset, dock | 1 each | 3 years |

Eligibility uses count and age only.

- Eligible when the person has fewer than the max, or the newest matching item is at least the refresh period old.
- Ineligible when they are at the max and the newest matching item is inside the refresh window. The result includes the next eligible date.
- Unknown when the employee is missing, the role is missing, or the item is not in the catalog.

The words in the reason do not change eligibility. They change deny versus escalate.

Exception words: `stolen`, `broken`, `cracked`, `accessibility`, `medical`, `accommodation`, `role change`.

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

The hash is SHA-256 of the canonical JSON of included facts. It is written once. The ledger stores memory id and reason code. Another employee's name and equipment stay out of the ledger and out of the prompt. A conflict makes eligibility for that item `unknown`.

## Tools

The agent calls these through MCP, on stdio and on HTTP. Both transports call the same service. Tests call the service directly.

| Tool | Result |
| --- | --- |
| `get_employee_info(employee_id)` | Role, start date, and equipment when that id is the included subject. `found: false` when the id is missing or excluded |
| `get_policy_limits(role)` | Max count and refresh years for included active rows. `found: false` for an unknown role |
| `check_request_eligibility(employee_id, item)` | `eligible`, `ineligible`, or `unknown`, plus the rule id and one line of detail |
| `flag_for_human_review(employee_id, request, reason)` | A new review id. An empty reason is rejected. The review stores the package hash |

## Decision

| Eligibility | Reason | Decision |
| --- | --- | --- |
| eligible | Ordinary first issue or refresh | approve |
| ineligible | Preference, extra item, or too soon, with no exception word | deny, citing the count or the next date from the package |
| ineligible | An exception word | escalate |
| unknown, missing employee, or a conflict | Any | escalate |

The reply may state only facts whose ids are in the included set.

## Stop, retry, and a person

The ReAct final answer is a proposal with `decision`, `reason`, and `cited_ids`. `decision` is only `approve`, `deny`, or `escalate`.

The worker accepts it when all of these hold:

1. Those three fields are present.
2. The reply hash equals the package hash on the request.
3. Every cited id is included.
4. The decision matches the table above.
5. An escalate has a review id from `flag_for_human_review`.

| Outcome | What the worker does |
| --- | --- |
| Checks pass | Status becomes `approved`, `denied`, or `escalated`. A person is involved only for `escalated` |
| First failure | Status returns to `queued`. Attempt becomes 1. The error is the next observation. The package stays frozen |
| Second failure | Both errors are logged. Status becomes `escalated`. Reason: `reply failed validation twice` |
| Worker dies while `running` | Status returns to `queued` as the same attempt |

Every stop writes the trace, the package hash, and an audit row. The log does not approve or deny.

Request statuses are `queued`, `running`, `approved`, `denied`, and `escalated`.

## Demo requests

`scripts/demo.py` runs these four and prints a Thought, Action, and Observation trace for each.

| Request | Expected |
| --- | --- |
| E1003: I need a laptop for my desk. | approve |
| E1001: I want a bigger second monitor. | deny. Next eligible date is 2027-11-01 |
| E1002: My laptop was stolen. I need a replacement. | escalate. Theft is inside the 2-year window |
| E1003: I need a drawing tablet for design work. | escalate. Tablet is not in the catalog |

## Chaos score

These run in `tests/server/test_context_chaos.py` on a temporary database. The worker does not inject them. CI is green when all three pass. The score does not approve equipment.

| Seed | Required result |
| --- | --- |
| ic monitor max 2 with `effective_to` last year | `exclude_stale_policy`. The hash keeps max 1 |
| E1002's laptop on a request for E1001 | `exclude_other_employee` and `exclude_other_equipment`. The hash omits Jordan's name and laptop |
| Two current ic laptop limits | `exclude_conflict` on both. Laptop eligibility is `unknown` |

## Layout

| Path | Job |
| --- | --- |
| `store/db.py` | Schema, WAL, connection |
| `store/repository.py` | SQL for employees, equipment, policies, requests, context packages, context decisions, review queue, and audit log |
| `store/seed.py` | The people and current policy above |
| `server/context.py` | Include, exclude, hash, ledger |
| `server/service.py` | Package, four operations, audit |
| `server/mcp.py` | The four tools on stdio and HTTP |
| `client/intake.py` | Insert a queued request |
| `client/worker.py` | Claim, validate, one retry, then escalate |
| `client/agent.py` | ReAct loop and reflection |
| `scripts/ask.py` | Submit one sentence |
| `scripts/queue.py` | Start the worker |
| `scripts/demo.py` | The four requests and their traces |
| `scripts/smoke.py` | One-tool stdio proof, before the other tools exist |
| `tests/store/` | Reads and a double claim |
| `tests/server/` | Service, package, chaos |
| `tests/client/` | Reflection and the three decisions |
| `.github/workflows/ci.yml` | Unit tests and the chaos score |

`store` imports nothing from `server` or `client`. `server` imports `store`. `client` claims rows through `store` and calls tools over MCP.

## Acceptance

- A missing employee id returns `found: false` and the request escalates.
- An empty escalation reason is rejected and no review row is written.
- Two workers cannot claim the same queued row.
- A tool call for another employee returns not-in-package and writes an audit row.
- A draft that says approved when eligibility was ineligible is not saved.
- `scripts/smoke.py` prints a real response from one tool before the other three are registered.
- CI runs the unit tests and the three chaos cases.

## Out of this version

Auth, a review screen, Postgres, a vector store, and a second queue. Several workers may share one SQLite file. Postgres is a later swap of `store/repository.py`.
