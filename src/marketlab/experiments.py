from __future__ import annotations
import hashlib
import uuid
from pathlib import Path
from .common import now
from .store import Store


class Experiment:
    """Records failed trials too; a crash leaves a visible STARTED event."""
    def __init__(self, private_dir, dataset, parameters):
        self.run_id = uuid.uuid4().hex
        self.db = Store(private_dir/"evidence.sqlite3")
        self.dataset, self.parameters = dataset, parameters
        self.output = None

    def __enter__(self):
        files = sorted(Path(__file__).parent.glob("*.py"))
        source_hash = hashlib.sha256(b"".join(p.name.encode()+p.read_bytes() for p in files)).hexdigest()
        dataset_hash = hashlib.sha256(self.dataset.read_bytes()).hexdigest() if self.dataset.exists() else None
        self.db.append("run_event", "research", self.run_id, {
            "state": "STARTED", "at": now(), "dataset_sha256": dataset_hash,
            "source_sha256": source_hash, "parameters": self.parameters})
        return self

    def __exit__(self, kind, error, tb):
        try:
            digest = hashlib.sha256(self.output.read_bytes()).hexdigest() if self.output and self.output.exists() else None
            self.db.append("run_event", "research", self.run_id, {
                "state": "FAILED" if kind else "COMPLETED", "at": now(),
                "error_type": kind.__name__ if kind else None, "result_sha256": digest})
        finally:
            self.db.close()
        return False
