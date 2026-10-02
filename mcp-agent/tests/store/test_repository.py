"""Unknown id and seed reads."""

from pathlib import Path

from store.db import connect, create_schema
from store.repository import get_employee, list_equipment, list_policies
from store.seed import seed


def _database(tmp_path: Path):
    connection = connect(tmp_path / "equipment.db")
    create_schema(connection)
    seed(connection)
    return connection


def test_known_employee_id(tmp_path: Path) -> None:
    connection = _database(tmp_path)

    employee = get_employee(connection, "E1001")

    assert employee is not None
    assert employee["name"] == "Priya Shah"
    assert employee["role"] == "ic"
    assert employee["start_date"] == "2021-03-01"
    equipment = list_equipment(connection, "E1001")
    assert [row["item"] for row in equipment] == ["laptop", "monitor"]
    policies = list_policies(connection, "ic")
    monitor = next(
        row for row in policies if row["item"] == "monitor" and row["effective_to"] is None
    )
    assert monitor["max_count"] == 1
    assert monitor["refresh_years"] == 3


def test_missing_employee_id(tmp_path: Path) -> None:
    connection = _database(tmp_path)

    assert get_employee(connection, "E9999") is None
    assert list_equipment(connection, "E9999") == []
