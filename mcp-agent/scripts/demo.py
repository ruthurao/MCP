"""Run the four graded requests and print traces."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
script_dir = ROOT / "scripts"
sys.path = [
    entry
    for entry in sys.path
    if not entry or Path(entry).resolve() != script_dir
]
sys.path.insert(0, str(ROOT))

from client.intake import open_database, submit
from client.reflection import reflect
from client.worker import run
from server.context import build_package

_REQUESTS = (
    "E1003: I need a laptop for my desk.",
    "E1001: I want a bigger second monitor.",
    "E1002: My laptop was stolen. I need a replacement.",
    "E1003: I need a drawing tablet for design work.",
)


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        connection = open_database(Path(directory) / "equipment.db")
        for sentence in _REQUESTS:
            submit(connection, sentence)
        finished = run(connection)
        for row in finished:
            print(f"{row['id']} {row['status']} {row['decision']}")
            print(row["reason"])
            print(row["trace"])
            print()

        priya = next(row for row in finished if row["employee_id"] == "E1001")
        package = build_package(connection, priya["id"])
        note, _proposal = reflect(
            package,
            {
                "decision": "deny",
                "reason": (
                    "Newest monitor is inside the 3-year window. "
                    "Next eligible 2027-11-01. Jordan Lee can spare a monitor."
                ),
                "cited_ids": ["employee:E1001"],
            },
        )
        print("Reflection catch")
        print(note)


if __name__ == "__main__":
    main()
