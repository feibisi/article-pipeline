"""SQLite database layer for article pipeline task queue."""
import json
import os
import sqlite3
from datetime import datetime, timezone


def _expand_path(path: str) -> str:
    """Expand ~ in path."""
    return os.path.expanduser(path)


class TaskDB:
    """Manages the article pipeline SQLite database."""

    def __init__(self, db_path: str = "~/docs/ai-context/article-pipeline.db"):
        self.db_path = _expand_path(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    # ── Schema migrations ──

    MIGRATIONS = [
        # 001: Initial schema
        (1, """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'wp-tech',
                platform TEXT NOT NULL DEFAULT 'wptea',
                priority INTEGER NOT NULL DEFAULT 2,
                status TEXT NOT NULL DEFAULT 'queued',
                research_note TEXT, outline TEXT, article TEXT, article_html TEXT,
                title TEXT, meta_description TEXT,
                meta_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                confirmed_at TEXT, published_at TEXT,
                published_url TEXT, skip_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS review_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                check_results TEXT NOT NULL DEFAULT '{}',
                passed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );
            CREATE TABLE IF NOT EXISTS review_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                reviewer TEXT NOT NULL, verdict TEXT NOT NULL, score REAL,
                feedback TEXT DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );
            CREATE INDEX IF NOT EXISTS idx_feedback_task ON review_feedback(task_id);
        """),
        # 002: Version tracking for iterative revision
        (2, """
            ALTER TABLE tasks ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
            ALTER TABLE tasks ADD COLUMN article_text_prev TEXT;
            ALTER TABLE review_log ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
            ALTER TABLE review_feedback ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
        """),
    ]

    def _migrate(self):
        """Run pending schema migrations in order."""
        c = self.conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        c.execute("SELECT COALESCE(MAX(version), 0) FROM _migrations")
        current = c.fetchone()[0]

        for ver, sql in self.MIGRATIONS:
            if ver <= current:
                continue
            try:
                for stmt in sql.strip().split(';'):
                    stmt = stmt.strip()
                    if stmt:
                        c.execute(stmt)
                c.execute("INSERT INTO _migrations (version) VALUES (?)", (ver,))
            except Exception as e:
                # Column already exists — migration was partially applied
                pass
        self.conn.commit()

    def add_task(self, keyword: str, category: str = "wp-tech",
                 platform: str = "wptea", priority: int = 2) -> int:
        c = self.conn.cursor()
        c.execute(
            "INSERT INTO tasks (keyword, category, platform, priority) "
            "VALUES (?, ?, ?, ?)",
            (keyword, category, platform, priority)
        )
        self.conn.commit()
        return c.lastrowid

    def get_task(self, task_id: int) -> dict | None:
        c = self.conn.cursor()
        c.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        row = c.fetchone()
        if not row:
            return None
        d = dict(row)
        d.setdefault("version", 1)
        d.setdefault("article_text_prev", "")
        return d

    def list_tasks(self, status: str | None = None,
                   category: str | None = None) -> list[dict]:
        query = "SELECT * FROM tasks WHERE 1=1"
        params: list = []
        if status:
            query += " AND status=?"
            params.append(status)
        if category:
            query += " AND category=?"
            params.append(category)
        query += " ORDER BY priority ASC, created_at ASC"
        c = self.conn.cursor()
        c.execute(query, params)
        return [dict(r) for r in c.fetchall()]

    def update_status(self, task_id: int, status: str,
                      meta: dict | None = None):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        fields = "status=?"
        params = [status]

        if status == "done" or status == "published":
            fields += ", published_at=?"
            params.append(now)
        elif status == "reviewing":
            fields += ", confirmed_at=?"
            params.append(now)

        params.append(task_id)
        c = self.conn.cursor()
        c.execute(f"UPDATE tasks SET {fields} WHERE id=?", params)

        if meta:
            c.execute("SELECT meta_json FROM tasks WHERE id=?", (task_id,))
            row = c.fetchone()
            existing = json.loads(row[0]) if row and row[0] else {}
            existing.update(meta)
            c.execute("UPDATE tasks SET meta_json=? WHERE id=?",
                      (json.dumps(existing, ensure_ascii=False), task_id))

        self.conn.commit()

    def save_stage_output(self, task_id: int, field: str, value: str):
        """Save research_note, outline, article, or article_html to a task."""
        allowed = {"research_note", "outline", "article", "article_html",
                   "title", "meta_description"}
        if field not in allowed:
            raise ValueError(f"Invalid field: {field}")
        c = self.conn.cursor()
        c.execute(f"UPDATE tasks SET {field}=? WHERE id=?", (value, task_id))
        self.conn.commit()

    def get_next_batch(self, limit: int = 5) -> list[dict]:
        """Claim next N queued tasks, set them to researching, return them."""
        c = self.conn.cursor()
        c.execute(
            "SELECT * FROM tasks WHERE status='queued' "
            "ORDER BY priority ASC, created_at ASC LIMIT ?",
            (limit,)
        )
        rows = [dict(r) for r in c.fetchall()]
        for r in rows:
            self.update_status(r["id"], "researching")
        return rows

    def add_review_entry(self, task_id: int, check_results: dict,
                         passed: bool = False):
        task = self.get_task(task_id)
        version = task.get("version", 1) if task else 1
        c = self.conn.cursor()
        c.execute(
            "INSERT INTO review_log (task_id, version, check_results, passed) "
            "VALUES (?, ?, ?, ?)",
            (task_id, version, json.dumps(check_results, ensure_ascii=False),
             int(passed))
        )
        self.conn.commit()

    def get_review_history(self, task_id: int) -> list[dict]:
        c = self.conn.cursor()
        c.execute(
            "SELECT id, version, check_results, passed, created_at "
            "FROM review_log WHERE task_id=? ORDER BY version ASC",
            (task_id,)
        )
        rows = []
        for r in c.fetchall():
            d = dict(r)
            d["check_results"] = json.loads(d.get("check_results", "{}"))
            rows.append(d)
        return rows

    def new_version(self, task_id: int, new_article: str) -> int:
        """Save article as a new version, keep previous version for diff."""
        task = self.get_task(task_id)
        old_version = task.get("version", 1) if task else 1
        new_ver = old_version + 1
        c = self.conn.cursor()
        c.execute(
            "UPDATE tasks SET version=?, article_text_prev=article, article=?, status='reviewing' WHERE id=?",
            (new_ver, new_article, task_id)
        )
        self.conn.commit()
        return new_ver

    def add_feedback(self, task_id: int, reviewer: str, verdict: str,
                     score: float = 0, feedback: dict | None = None):
        task = self.get_task(task_id)
        version = task.get("version", 1) if task else 1
        c = self.conn.cursor()
        c.execute(
            "INSERT INTO review_feedback (task_id, version, reviewer, verdict, score, feedback) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, version, reviewer, verdict, score,
             json.dumps(feedback or {}, ensure_ascii=False))
        )
        self.conn.commit()

    def get_latest_feedback(self, task_id: int) -> dict | None:
        c = self.conn.cursor()
        c.execute(
            "SELECT * FROM review_feedback WHERE task_id=? ORDER BY id DESC LIMIT 1",
            (task_id,)
        )
        row = c.fetchone()
        if row:
            d = dict(row)
            d["feedback"] = json.loads(d.get("feedback", "{}"))
            return d
        return None

    def get_feedback_history(self, task_id: int) -> list[dict]:
        c = self.conn.cursor()
        c.execute(
            "SELECT * FROM review_feedback WHERE task_id=? ORDER BY id ASC",
            (task_id,)
        )
        results = []
        for row in c.fetchall():
            d = dict(row)
            d["feedback"] = json.loads(d.get("feedback", "{}"))
            results.append(d)
        return results


def init_db(db_path: str = "~/docs/ai-context/article-pipeline.db") -> TaskDB:
    """Initialize and return a TaskDB instance."""
    return TaskDB(db_path=db_path)
