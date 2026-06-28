from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,           -- 'resolve' | 'reconcile'
    key TEXT NOT NULL,            -- dedupe/cooldown key (e.g. file path, or missing-track id)
    action TEXT NOT NULL,         -- 'apply' | 'needs_review' | 'skip'
    candidate_summary TEXT,
    confidence REAL,
    reasoning TEXT,
    applied INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_decisions_key ON decisions(key);
"""


class DecisionStore:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db_path = db_path
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def record_decision(
        self,
        *,
        kind: str,
        key: str,
        action: str,
        candidate_summary: str | None,
        confidence: float,
        reasoning: str,
        applied: bool,
    ) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """INSERT INTO decisions
                   (created_at, kind, key, action, candidate_summary, confidence, reasoning, applied)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    kind,
                    key,
                    action,
                    candidate_summary,
                    confidence,
                    reasoning,
                    1 if applied else 0,
                ),
            )
            conn.commit()

    def recently_processed(self, kind: str, key: str, cooldown_minutes: int) -> bool:
        """True if this key already has a decision within the cooldown window.
        Applied imports are excluded - if Lidarr still reports the file as needing
        import after we applied a fix, something's wrong and it deserves another look,
        not a silent skip."""
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)).isoformat()
        with closing(self._connect()) as conn:
            row = conn.execute(
                """SELECT 1 FROM decisions
                   WHERE kind = ? AND key = ? AND created_at >= ? AND applied = 0
                   LIMIT 1""",
                (kind, key, cutoff),
            ).fetchone()
        return row is not None
