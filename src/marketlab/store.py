"""Append-only evidence. Publication time and observation time remain distinct."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .common import now, timestamp


class Store:
    def __init__(self, path: Path, max_bytes=256 * 1024 * 1024):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.max_bytes = path, max_bytes
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS observations (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, source TEXT NOT NULL,
                subject TEXT NOT NULL, published_at TEXT, received_at TEXT NOT NULL,
                available_at TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS observation_lookup ON observations(kind, subject, available_at);
            CREATE TABLE IF NOT EXISTS receipts (
                observation_id TEXT NOT NULL, received_at TEXT NOT NULL,
                PRIMARY KEY(observation_id, received_at)
            );
            CREATE TRIGGER IF NOT EXISTS observations_no_update BEFORE UPDATE ON observations
              BEGIN SELECT RAISE(ABORT, 'append-only'); END;
            CREATE TRIGGER IF NOT EXISTS observations_no_delete BEFORE DELETE ON observations
              BEGIN SELECT RAISE(ABORT, 'append-only'); END;
            CREATE TRIGGER IF NOT EXISTS receipts_no_update BEFORE UPDATE ON receipts
              BEGIN SELECT RAISE(ABORT, 'append-only'); END;
            CREATE TRIGGER IF NOT EXISTS receipts_no_delete BEFORE DELETE ON receipts
              BEGIN SELECT RAISE(ABORT, 'append-only'); END;
        """)

    def append(self, kind, source, subject, payload, *, published_at=None, received_at=None):
        received = timestamp(received_at) if received_at else now()
        published = timestamp(published_at) if published_at else None
        available = max(received, published) if published else received
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str, allow_nan=False)
        # Deduplicate identical source content, preserving the first observation.
        key = hashlib.sha256(json.dumps([kind, source, subject, str(published), body]).encode()).hexdigest()
        size = sum(p.stat().st_size for p in self.path.parent.glob(self.path.name + "*") if p.is_file())
        if size + len(body.encode()) > self.max_bytes:
            raise RuntimeError("Evidence quota reached; back up and explicitly rotate the database")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (key, kind, source, subject, published.isoformat() if published else None,
                             received.isoformat(), available.isoformat(), body))
            self.db.execute("INSERT OR IGNORE INTO receipts VALUES (?, ?)", (key, received.isoformat()))
        return key

    def as_of(self, kind, subject, cutoff):
        t = timestamp(cutoff).isoformat()
        rows = self.db.execute(
            "SELECT id,payload,available_at FROM observations WHERE kind=? AND subject=? "
            "AND available_at<=? ORDER BY available_at,id", (kind, subject, t)).fetchall()
        return [{"id": r[0], "payload": json.loads(r[1]), "available_at": r[2]} for r in rows]

    def count(self):
        return self.db.execute("SELECT count(*) FROM observations").fetchone()[0]

    def backup(self, destination: Path):
        if destination.resolve() == self.path.resolve():
            raise ValueError("Choose a different backup destination")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destination) as target:
            self.db.backup(target)

    def close(self):
        self.db.close()
