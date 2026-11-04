"""Append-only evidence. Publication time, first-known time and each receipt time remain distinct.

Two different questions are answered from different columns:

* "Since when has this document been known?"  ``observations.received_at`` (first receipt). Used for
  point-in-time research (``as_of``), so later receipts never back-date a document.
* "What is the current state?"  The latest eligible *receipt* (``latest``). Identical bytes received
  again are stored once but receive a new receipt row, so for A -> B -> A the second A is current even
  though its bytes were first stored before B (review finding on snapshot chronology).

Receipts written by one collection run share a ``batch_id``; account views use one completed batch so
that a kind missing from the newest batch is reported as unknown instead of silently showing an
older snapshot.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .common import now, timestamp


def _iso(t):
    return t.isoformat(timespec="microseconds")


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
        columns = {r[1] for r in self.db.execute("PRAGMA table_info(receipts)")}
        if "batch_id" not in columns:  # schema v2; older receipts keep a NULL batch (legacy)
            with self.db:
                self.db.execute("ALTER TABLE receipts ADD COLUMN batch_id TEXT")
        self.db.execute("CREATE INDEX IF NOT EXISTS receipt_observation ON receipts(observation_id)")

    def append(self, kind, source, subject, payload, *, published_at=None, received_at=None, batch_id=None):
        received = timestamp(received_at) if received_at else now()
        published = timestamp(published_at) if published_at else None
        available = max(received, published) if published else received
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str, allow_nan=False)
        # Deduplicate identical source content, preserving the first observation; every receipt is kept.
        key = hashlib.sha256(json.dumps([kind, source, subject, str(published), body]).encode()).hexdigest()
        size = sum(p.stat().st_size for p in self.path.parent.glob(self.path.name + "*") if p.is_file())
        if size + len(body.encode()) > self.max_bytes:
            raise RuntimeError("Evidence quota reached; back up and explicitly rotate the database")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (key, kind, source, subject, _iso(published) if published else None,
                             _iso(received), _iso(available), body))
            self.db.execute("INSERT OR IGNORE INTO receipts(observation_id, received_at, batch_id) VALUES (?, ?, ?)",
                            (key, _iso(received), batch_id))
        return key

    def as_of(self, kind, subject, cutoff):
        """Documents first known (and published) by ``cutoff``, oldest first. For point-in-time research."""
        t = timestamp(cutoff)
        rows = self.db.execute(
            "SELECT id,payload,available_at FROM observations WHERE kind=? AND subject=?", (kind, subject)).fetchall()
        rows = [r for r in rows if timestamp(r[2]) <= t]
        rows.sort(key=lambda r: (timestamp(r[2]), r[0]))
        return [{"id": r[0], "payload": json.loads(r[1]), "available_at": r[2]} for r in rows]

    def latest(self, kind, subject, cutoff=None, *, batch_id=None):
        """The current state: the document with the latest receipt at or before ``cutoff``.

        With ``batch_id`` only receipts from that collection batch are eligible. Returns ``None`` when
        nothing is eligible. ``first_received_at`` is when these exact bytes were first known.
        """
        cut = timestamp(cutoff) if cutoff else now()
        rows = self.db.execute(
            "SELECT r.observation_id, r.received_at, r.batch_id, o.published_at FROM receipts r "
            "JOIN observations o ON o.id = r.observation_id WHERE o.kind=? AND o.subject=?",
            (kind, subject)).fetchall()
        best = None
        for oid, received, batch, published in rows:
            t = timestamp(received)
            if t > cut or (published and timestamp(published) > cut):
                continue
            if batch_id is not None and batch != batch_id:
                continue
            if best is None or t > best[0]:
                best = (t, oid, batch)
        if best is None:
            return None
        payload, first, published = self.db.execute(
            "SELECT payload, received_at, published_at FROM observations WHERE id=?", (best[1],)).fetchone()
        return {"id": best[1], "payload": json.loads(payload), "received_at": _iso(best[0]),
                "first_received_at": first, "published_at": published, "batch_id": best[2]}

    def latest_by_source(self, kind):
        """{source: newest receipt time} for one kind (all receipts of that kind, any subject)."""
        out = {}
        for source, received in self.db.execute(
                "SELECT o.source, r.received_at FROM receipts r JOIN observations o ON o.id = r.observation_id "
                "WHERE o.kind=?", (kind,)):
            t = timestamp(received)
            if source not in out or t > out[source]:
                out[source] = t
        return out

    def recent(self, kind, limit=30):
        """Newest documents of a kind by first receipt (for timelines)."""
        rows = self.db.execute("SELECT id, subject, payload, received_at FROM observations WHERE kind=?", (kind,)).fetchall()
        rows.sort(key=lambda r: timestamp(r[3]), reverse=True)
        return [{"id": r[0], "subject": r[1], "payload": json.loads(r[2]), "received_at": r[3]} for r in rows[:limit]]

    def receipts(self, observation_id):
        return [r[0] for r in self.db.execute(
            "SELECT received_at FROM receipts WHERE observation_id=? ORDER BY received_at", (observation_id,))]

    def count(self):
        return self.db.execute("SELECT count(*) FROM observations").fetchone()[0]

    def size_bytes(self):
        return sum(p.stat().st_size for p in self.path.parent.glob(self.path.name + "*") if p.is_file())

    def backup(self, destination: Path):
        if destination.resolve() == self.path.resolve():
            raise ValueError("Choose a different backup destination")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destination) as target:
            self.db.backup(target)

    def close(self):
        self.db.close()
