import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from app.business import DomainIssue

SCHEMA = """CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, report TEXT NOT NULL, created TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', revision INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '', reviewed TEXT
);"""


class Store:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=15)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute(SCHEMA)
            yield db

    def register(self, run_id, report):
        with self.connect() as db:
            db.execute(
                "INSERT INTO runs(id,report,created) VALUES (?,?,?) ON CONFLICT(id) DO NOTHING",
                (
                    run_id,
                    json.dumps(report, ensure_ascii=False),
                    report["manifest"]["created"],
                ),
            )
        return self.load(run_id)

    def load(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise DomainIssue("RUN_NOT_FOUND")
        result = dict(row)
        result["report"] = json.loads(result["report"])
        return result

    def list(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,created,status,revision,note FROM runs ORDER BY created DESC,id LIMIT 50"
                )
            ]

    def baseline_for(self, conversions, run_id=None):
        """取与本次转化集合有交集的最新批次作为增量重算基线。

        排除本次批次自身，避免并发重跑把自身当成上游而自我循环；没有
        交集的历史批次不参与血缘，避免把无关来源记成旧版证据。
        """
        wanted = set(conversions)
        if not wanted:
            return None
        with self.connect() as db:
            if run_id is None:
                rows = db.execute(
                    "SELECT * FROM runs ORDER BY rowid DESC LIMIT 50"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM runs WHERE id<>? ORDER BY rowid DESC LIMIT 50",
                    (run_id,),
                ).fetchall()
        for row in rows:
            result = dict(row)
            result["report"] = json.loads(result["report"])
            records = {
                entry.get("record")
                for entry in result["report"].get("ledger", {}).get("entries", [])
            }
            if records & wanted:
                return result
        return None

    def versions(self, run_id):
        """沿 manifest.parent 回溯，返回该批次的旧版证据链。"""
        chain, seen = [], set()
        current = run_id
        while current and current not in seen:
            seen.add(current)
            try:
                run = self.load(current)
            except DomainIssue:
                break
            manifest = run["report"].get("manifest", {})
            chain.append(
                {
                    "id": run["id"],
                    "created": run["created"],
                    "status": run["status"],
                    "revision": run["revision"],
                    "sha256": manifest.get("sha256"),
                    "parent": manifest.get("parent"),
                    "reused": run["report"].get("lineage", {}).get("reused", []),
                    "recomputed": run["report"].get("lineage", {}).get(
                        "recomputed", []
                    ),
                }
            )
            current = manifest.get("parent")
        return chain

    def revise(self, run_id, revision, status, note, now):
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE runs SET status=?,note=?,reviewed=?,revision=revision+1 WHERE id=? AND revision=?",
                (status, note, now, run_id, revision),
            )
            if cursor.rowcount != 1:
                raise DomainIssue("STALE_REVIEW")
        return self.load(run_id)
