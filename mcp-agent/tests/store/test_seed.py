"""A temporary database contains the three seeded employees and not E9999."""

from pathlib import Path

from store.db import connect, create_schema
from store.seed import seed


def test_seed_has_the_three_employees_and_not_the_missing_id(tmp_path: Path) -> None:
    connection = connect(tmp_path / "equipment.db")
    create_schema(connection)
    seed(connection)

    employees = {
        row["employee_id"]: row
        for row in connection.execute(
            "SELECT employee_id, name, role, start_date FROM employees ORDER BY employee_id"
        )
    }

    assert list(employees) == ["E1001", "E1002", "E1003"]
    assert employees["E1001"]["name"] == "Priya Shah"
    assert employees["E1001"]["role"] == "ic"
    assert employees["E1001"]["start_date"] == "2021-03-01"
    assert employees["E1002"]["name"] == "Jordan Lee"
    assert employees["E1002"]["role"] == "manager"
    assert employees["E1003"]["name"] == "Alex Kim"
    assert employees["E1003"]["role"] == "ic"
    assert (
        connection.execute(
            "SELECT COUNT(*) AS count FROM employees WHERE employee_id = ?",
            ("E9999",),
        ).fetchone()["count"]
        == 0
    )


def test_seed_equipment_and_current_policy(tmp_path: Path) -> None:
    connection = connect(tmp_path / "equipment.db")
    create_schema(connection)
    seed(connection)

    priya = connection.execute(
        """
        SELECT item, issued_on FROM equipment
        WHERE employee_id = ? ORDER BY item
        """,
        ("E1001",),
    ).fetchall()
    assert [(row["item"], row["issued_on"]) for row in priya] == [
        ("laptop", "2021-04-01"),
        ("monitor", "2024-11-01"),
    ]

    alex_equipment = connection.execute(
        "SELECT COUNT(*) AS count FROM equipment WHERE employee_id = ?",
        ("E1003",),
    ).fetchone()["count"]
    assert alex_equipment == 0

    monitor = connection.execute(
        """
        SELECT max_count, refresh_years, effective_to
        FROM policies
        WHERE role = ? AND item = ?
        """,
        ("ic", "monitor"),
    ).fetchone()
    assert monitor["max_count"] == 1
    assert monitor["refresh_years"] == 3
    assert monitor["effective_to"] is None

    manager_monitor = connection.execute(
        """
        SELECT max_count, refresh_years FROM policies
        WHERE role = ? AND item = ?
        """,
        ("manager", "monitor"),
    ).fetchone()
    assert manager_monitor["max_count"] == 2
    assert manager_monitor["refresh_years"] == 3

    assert (
        connection.execute("SELECT COUNT(*) AS count FROM policies").fetchone()["count"]
        == 10
    )
    assert (
        connection.execute("SELECT COUNT(*) AS count FROM requests").fetchone()["count"]
        == 0
    )


def test_connection_uses_wal(tmp_path: Path) -> None:
    connection = connect(tmp_path / "equipment.db")
    mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
