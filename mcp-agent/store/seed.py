"""Employees, their equipment, current policy, and two expired rows."""

import sqlite3

_EMPLOYEES = (
    ("E1001", "Priya Shah", "ic", "2021-03-01"),
    ("E1002", "Jordan Lee", "manager", "2019-01-15"),
    ("E1003", "Alex Kim", "ic", "2024-08-01"),
    ("E1004", "Nora Patel", "ic", "2022-05-01"),
    ("E1005", "Chris Adeyemi", "ic", "2019-02-01"),
    ("E1006", "Taylor Brooks", "manager", "2018-06-01"),
    ("E1007", "Mina Cho", "ic", "2020-09-01"),
    ("E1008", "Owen Garcia", "manager", "2017-04-01"),
    ("E1009", "Lila Hassan", "ic", "2021-11-01"),
    ("E1010", "Riley Chen", "executive", "2016-01-04"),
)

_EQUIPMENT = (
    ("E1001", "laptop", "2021-04-01"),
    ("E1001", "monitor", "2024-11-01"),
    ("E1002", "laptop", "2025-02-01"),
    ("E1002", "monitor", "2023-01-10"),
    ("E1002", "monitor", "2024-06-01"),
    ("E1004", "monitor", "2023-09-30"),
    ("E1005", "monitor", "2024-02-29"),
    ("E1006", "monitor", "2024-08-01"),
    ("E1007", "laptop", "2022-09-30"),
    ("E1007", "keyboard", "2025-01-15"),
    ("E1008", "laptop", "2024-01-15"),
    ("E1009", "headset", "2025-03-01"),
    ("E1009", "docking_station", "2023-09-30"),
    ("E1010", "laptop", "2025-06-01"),
)

_POLICIES = (
    ("ic", "laptop", 1, 4),
    ("ic", "monitor", 1, 3),
    ("ic", "keyboard", 1, 3),
    ("ic", "headset", 1, 3),
    ("ic", "docking_station", 1, 3),
    ("manager", "laptop", 1, 2),
    ("manager", "monitor", 2, 3),
    ("manager", "keyboard", 1, 3),
    ("manager", "headset", 1, 3),
    ("manager", "docking_station", 1, 3),
    ("executive", "laptop", 1, 2),
    ("executive", "monitor", 2, 2),
    ("executive", "keyboard", 1, 2),
    ("executive", "headset", 1, 2),
    ("executive", "docking_station", 1, 2),
)

_EFFECTIVE_FROM = "2020-01-01"

# Expired rows sit beside the current ones. They stay out of a package.
_STALE_POLICIES = (
    ("ic", "monitor", 2, 3, "2020-01-01", "2025-09-30"),
    ("ic", "laptop", 2, 4, "2020-01-01", "2024-12-31"),
)


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
    connection.executemany(
        """
        INSERT INTO policies (
            role, item, max_count, refresh_years, effective_from, effective_to
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        _STALE_POLICIES,
    )
    connection.commit()
