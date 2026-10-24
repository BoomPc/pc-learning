from __future__ import annotations
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

TERMINAL = {"completed", "failed", "needs_input", "cancelled", "interrupted"}


def write_json(path: Path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


class Store:
    def __init__(self, root: Path):
        self.root = root
        (root / "jobs").mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = root / "jobs.sqlite3"
        with self.connection() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript('''CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, status TEXT NOT NULL, stage TEXT NOT NULL,
              created REAL NOT NULL, updated REAL NOT NULL, error TEXT, summary TEXT);
              CREATE TABLE IF NOT EXISTS events (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
              at REAL NOT NULL, stage TEXT NOT NULL, detail TEXT NOT NULL);''')

    @contextmanager
    def connection(self):
        c = sqlite3.connect(self.db, timeout=15)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def path(self, job_id):
        if not isinstance(job_id, str) or len(job_id) != 32 or any(x not in "0123456789abcdef" for x in job_id):
            raise ValueError("无效任务编号")
        return self.root / "jobs" / job_id

    def prepare(self):
        job_id = uuid.uuid4().hex
        self.path(job_id).mkdir(mode=0o700)
        return job_id, self.path(job_id)

    def enqueue(self, job_id):
        now = time.time()
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] >= 20:
                raise ValueError("任务队列已满，请稍后再试")
            c.execute("INSERT INTO jobs VALUES (?, 'queued', 'queued', ?, ?, NULL, NULL)", (job_id, now, now))

    def claim(self):
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if row:
                c.execute("UPDATE jobs SET status='running',stage='starting',updated=? WHERE id=?", (time.time(), row[0]))
                return row[0]

    def get(self, job_id):
        self.path(job_id)
        with self.connection() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["summary"] = json.loads(result["summary"]) if result["summary"] else None
            result["events"] = [dict(r) for r in c.execute("SELECT at,stage,detail FROM events WHERE job_id=? ORDER BY seq DESC LIMIT 50", (job_id,))][::-1]
            return result

    def event(self, job_id, stage, detail=""):
        with self.connection() as c:
            c.execute("INSERT INTO events(job_id,at,stage,detail) VALUES (?,?,?,?)", (job_id, time.time(), stage, str(detail)[:2000]))
            c.execute("UPDATE jobs SET stage=?,updated=? WHERE id=? AND status='running'", (stage, time.time(), job_id))

    def finish(self, job_id, status, error=None, summary=None):
        if status not in TERMINAL:
            raise ValueError("无效终态")
        with self.connection() as c:
            c.execute("UPDATE jobs SET status=?,stage=?,error=?,summary=?,updated=? WHERE id=? AND status IN ('queued','running')",
                      (status, status, error, json.dumps(summary, ensure_ascii=False) if summary else None, time.time(), job_id))

    def recover(self):
        with self.connection() as c:
            c.execute("UPDATE jobs SET status='interrupted',stage='interrupted',error='Worker 重启，任务中断；未自动重新调用付费模型',updated=? WHERE status='running'", (time.time(),))

