import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .domain import now_iso


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.db_path = root / "research.sqlite3"
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, prompt TEXT NOT NULL,
                    mode TEXT NOT NULL, status TEXT NOT NULL, spec TEXT, bundle_path TEXT,
                    error TEXT, parent_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    kind TEXT NOT NULL, label TEXT NOT NULL, payload TEXT NOT NULL, at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_run ON events(run_id, seq);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
            if "refresh_requested" not in columns:
                db.execute("ALTER TABLE runs ADD COLUMN refresh_requested INTEGER NOT NULL DEFAULT 0")
            if "export_reports" not in columns:
                db.execute("ALTER TABLE runs ADD COLUMN export_reports INTEGER NOT NULL DEFAULT 1")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def create(
        self,
        prompt: str,
        mode: str = "live",
        spec: dict | None = None,
        parent_id: str | None = None,
        run_id: str | None = None,
        refresh: bool = False,
        export_reports: bool = True,
    ) -> str:
        run_id = run_id or uuid.uuid4().hex[:16]
        stamp = now_iso()
        with self.db() as db:
            db.execute(
                "INSERT INTO runs (id,title,prompt,mode,status,spec,parent_id,created_at,updated_at,refresh_requested,export_reports) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    spec.get("title", prompt[:80]) if spec else prompt[:80],
                    prompt,
                    mode,
                    "queued",
                    json.dumps(spec, ensure_ascii=False) if spec else None,
                    parent_id,
                    stamp,
                    stamp,
                    int(refresh),
                    int(export_reports),
                ),
            )
        return run_id

    def update(self, run_id: str, *, expected: set[str] | None = None, **values) -> bool:
        allowed = {"title", "status", "spec", "bundle_path", "error"}
        if not values or set(values) - allowed:
            raise ValueError("Invalid run fields")
        values["updated_at"] = now_iso()
        if isinstance(values.get("spec"), dict):
            values["spec"] = json.dumps(values["spec"], ensure_ascii=False)
        assignments = ", ".join(f"{key}=?" for key in values)
        guard = " AND status IN (" + ",".join("?" for _ in expected) + ")" if expected else ""
        with self.db() as db:
            result = db.execute(
                f"UPDATE runs SET {assignments} WHERE id=?{guard}",
                (*values.values(), run_id, *(expected or [])),
            )
            return result.rowcount == 1

    def get(self, run_id: str) -> dict | None:
        with self.db() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["spec"] = json.loads(result["spec"]) if result["spec"] else None
        return result

    def list_runs(self) -> list[dict]:
        with self.db() as db:
            rows = db.execute(
                "SELECT id, title, mode, status, created_at, updated_at, error, parent_id "
                "FROM runs WHERE mode IN ('live','sample') ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return [dict(row) for row in rows]

    def emit(self, run_id: str, kind: str, label: str, **payload):
        with self.db() as db:
            db.execute(
                "INSERT INTO events(run_id,kind,label,payload,at) VALUES (?,?,?,?,?)",
                (run_id, kind, label, json.dumps(payload, ensure_ascii=False, default=str), now_iso()),
            )

    def events(self, run_id: str, after: int = 0) -> list[dict]:
        with self.db() as db:
            rows = db.execute(
                "SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 500", (run_id, after)
            ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def chat_history(self, run_id: str, limit: int = 100) -> list[dict]:
        with self.db() as db:
            rows = db.execute(
                "SELECT payload FROM events WHERE run_id=? AND kind='chat' ORDER BY seq DESC LIMIT ?",
                (run_id, limit),
            ).fetchall()
        return [json.loads(row["payload"]) for row in reversed(rows)]

    def clarification_context(self, run: dict) -> tuple[dict | None, list[dict]]:
        """Recover a bounded clarification chain, including the last concrete specification."""
        context = []
        parent_id = run.get("parent_id")
        seen = {run["id"]}
        while parent_id and parent_id not in seen and len(context) < 10:
            seen.add(parent_id)
            parent = self.get(parent_id)
            if not parent:
                break
            if parent["status"] != "needs_input":
                return parent.get("spec"), list(reversed(context))
            context.append({"request": parent["prompt"], "question": parent["error"]})
            parent_id = parent.get("parent_id")
        return None, list(reversed(context))

    def run_dir(self, run_id: str) -> Path:
        if not run_id.isalnum() or len(run_id) > 64:
            raise ValueError("Invalid run ID")
        path = self.root / "runs" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_json(self, path: Path, value: Any):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, default=str))
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def recover(self):
        with self.db() as db:
            db.execute("UPDATE runs SET status='queued' WHERE status='running' AND mode='live'")

    def claim_next_queued(self) -> dict | None:
        with self.db() as db:
            row = db.execute(
                "UPDATE runs SET status='running', updated_at=? WHERE id=("
                "SELECT id FROM runs WHERE status='queued' AND mode='live' ORDER BY created_at LIMIT 1"
                ") AND status='queued' RETURNING id",
                (now_iso(),),
            ).fetchone()
        return self.get(row["id"]) if row else None
