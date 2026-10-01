"""Hash and ledger on a normal request."""

import hashlib
import json
from pathlib import Path

from server.context import build_package
from store.db import connect, create_schema
from store.repository import get_request, insert_request
from store.seed import seed


def _request(tmp_path: Path) -> tuple:
    connection = connect(tmp_path / "equipment.db")
    create_schema(connection)
    seed(connection)
    request_id = insert_request(
        connection,
        employee_id="E1001",
        item="monitor",
        reason="I want a bigger second monitor.",
        submitted_on="2026-09-30",
    )
    return connection, request_id


def test_normal_request_hashes_only_included_facts(tmp_path: Path) -> None:
    connection, request_id = _request(tmp_path)

    package = build_package(connection, request_id)

    included_ids = {fact["memory_id"] for fact in package["included"]}
    assert "employee:E1001" in included_ids
    assert any(
        fact["kind"] == "equipment" and fact["item"] == "monitor"
        for fact in package["included"]
    )
    assert any(
        fact["kind"] == "equipment" and fact["item"] == "laptop"
        for fact in package["included"]
    )
    assert any(
        fact["kind"] == "policy"
        and fact["role"] == "ic"
        and fact["item"] == "monitor"
        and fact["max_count"] == 1
        for fact in package["included"]
    )
    assert "employee:E1002" not in included_ids
    assert "employee:E1003" not in included_ids
    assert "Jordan" not in package["canonical_json"]
    assert "2025-02-01" not in package["canonical_json"]
    digest = hashlib.sha256(package["canonical_json"].encode()).hexdigest()
    assert package["content_hash"] == digest
    assert package["conflict"] is False

    stored_request = get_request(connection, request_id)
    assert stored_request["context_hash"] == package["content_hash"]

    excluded = [
        decision
        for decision in package["decisions"]
        if decision["outcome"] == "exclude"
    ]
    assert {
        decision["memory_id"]: decision["reason_code"] for decision in excluded
    }["employee:E1002"] == "exclude_other_employee"
    ledger_text = json.dumps(package["decisions"])
    assert "Jordan" not in ledger_text
    assert "Priya" not in ledger_text
    assert "2025-02-01" not in ledger_text


def test_package_is_written_once(tmp_path: Path) -> None:
    connection, request_id = _request(tmp_path)
    first = build_package(connection, request_id)

    connection.execute(
        """
        UPDATE policies
        SET max_count = 9
        WHERE role = 'ic' AND item = 'monitor'
        """
    )
    second = build_package(connection, request_id)

    assert second["package_id"] == first["package_id"]
    assert second["content_hash"] == first["content_hash"]
    assert second["canonical_json"] == first["canonical_json"]
    assert '"max_count":1' in second["canonical_json"]
