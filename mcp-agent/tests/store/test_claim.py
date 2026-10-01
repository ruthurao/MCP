"""Two workers cannot own the same row."""

from __future__ import annotations

import threading
from pathlib import Path

from store.db import connect, create_schema
from store.repository import claim_next, insert_request
from store.seed import seed


def _database(tmp_path: Path):
    connection = connect(tmp_path / "equipment.db")
    create_schema(connection)
    seed(connection)
    return connection


def test_second_claim_finds_nothing(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    request_id = insert_request(
        connection,
        employee_id="E1003",
        item="laptop",
        reason="I need a laptop for my desk.",
        submitted_on="2026-09-30",
    )

    first = claim_next(connection)
    second = claim_next(connection)

    assert first is not None
    assert first["id"] == request_id
    assert first["status"] == "running"
    assert second is None


def test_two_connections_cannot_claim_the_same_row(tmp_path: Path) -> None:
    path = tmp_path / "equipment.db"
    connection = connect(path)
    create_schema(connection)
    seed(connection)
    request_id = insert_request(
        connection,
        employee_id="E1001",
        item="monitor",
        reason="I want a bigger second monitor.",
        submitted_on="2026-09-30",
    )
    connection.close()

    barrier = threading.Barrier(2)
    claimed: list[int | None] = []
    errors: list[BaseException] = []

    def worker() -> None:
        worker_connection = connect(path)
        try:
            barrier.wait()
            row = claim_next(worker_connection)
            claimed.append(None if row is None else row["id"])
        except BaseException as exc:
            errors.append(exc)
        finally:
            worker_connection.close()

    threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sorted(claimed, key=lambda value: (value is None, value)) == [
        request_id,
        None,
    ]
    status = connect(path).execute(
        "SELECT status FROM requests WHERE id = ?",
        (request_id,),
    ).fetchone()["status"]
    assert status == "running"
