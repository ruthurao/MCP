"""Three employees and the current policy rows."""

import sqlite3

_EMPLOYEES = (
    ("E1001", "Priya Shah", "ic", "2021-03-01"),
    ("E1002", "Jordan Lee", "manager", "2019-01-15"),
    ("E1003", "Alex Kim", "ic", "2024-08-01"),
)

_EQUIPMENT = (
    ("E1001", "laptop", "2021-04-01"),
    ("E1001", "monitor", "2024-11-01"),
    ("E1002", "laptop", "2025-02-01"),
    ("E1002", "monitor", "2023-01-10"),
    ("E1002", "monitor", "2024-06-01"),
)

_POLICIES = (
    ("ic", "laptop", 1, 4),
    ("ic", "monitor", 1, 3),
    ("ic", "keyboard", 1, 3),
    ("ic", "headset", 1, 3),
    ("ic", "dock", 1, 3),
    ("manager", "laptop", 1, 2),
    ("manager", "monitor", 2, 3),
    ("manager", "keyboard", 1, 3),
    ("manager", "headset", 1, 3),
    ("manager", "dock", 1, 3),
)

_EFFECTIVE_FROM = "2020-01-01"


def seed(connection: sqlite3.Connection) -> None:
    connection.executemany(
        "INSERT INTO employees (employee_id, name, role, start_date) VALUES (?, ?, ?, ?)",
        _EMPLOYEES,
    )
    connection.executemany(
        "INSERT INTO equipment (employee_id, item, issued_on) VALUES (?, ?, ?)",
        _EQUIPMENT,
    )
    connection.executemany(
        """
        INSERT INTO policies (
            role, item, max_count, refresh_years, effective_from, effective_to
        ) VALUES (?, ?, ?, ?, ?, NULL)
        """,
        [(*policy, _EFFECTIVE_FROM) for policy in _POLICIES],
    )
    connection.commit()
