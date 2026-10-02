"""Submit one equipment request."""

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

from client.intake import open_database, submit


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Queue one equipment sentence.")
    parser.add_argument("--db", required=True)
    parser.add_argument("sentence")
    args = parser.parse_args(argv)
    connection = open_database(args.db)
    try:
        request_id = submit(connection, args.sentence)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(f"{request_id} queued")


if __name__ == "__main__":
    main()
