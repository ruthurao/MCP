"""Claim queued requests until the queue is empty."""

from __future__ import annotations

import sqlite3

from store.repository import claim_next


def run(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    claimed: list[sqlite3.Row] = []
    while True:
        row = claim_next(connection)
        if row is None:
            return claimed
        claimed.append(row)
