"""Start the worker on queued requests."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
script_dir = ROOT / "scripts"
sys.path = [
    entry
    for entry in sys.path
    if not entry or Path(entry).resolve() != script_dir
]
sys.path.insert(0, str(ROOT))

from client.intake import open_database
from client.worker import run


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Claim every queued request.")
    parser.add_argument("--db", required=True)
    args = parser.parse_args(argv)
    connection = open_database(args.db)
    claimed = run(connection)
    if not claimed:
        print("queue empty")
        return
    for row in claimed:
        print(f"{row['id']} running")


if __name__ == "__main__":
    main()
