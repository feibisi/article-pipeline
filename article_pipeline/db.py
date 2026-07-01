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

    def __init__(self, db_path: str = "~/docs/ai-context/article-pipeline-v1.db"):
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
        # 003: Cascade layer intermediate outputs
        (3, """
            ALTER TABLE tasks ADD COLUMN synthesis TEXT;
            ALTER TABLE tasks ADD COLUMN framework TEXT;
            ALTER TABLE tasks ADD COLUMN prosody TEXT;
            ALTER TABLE tasks ADD COLUMN compiled_prompt TEXT;
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
                if "duplicate column" not in str(e).lower():
                    import sys
                    print(f"[db] migration v{ver} warning: {e}", file=sys.stderr)
        self.conn.commit()

    def add_task(self, keyword: str, category: str = "wp-tech",
                 platform: str = "wptea", priority: int = 2,
                 allow_duplicate: bool = False) -> int | None:
        c = self.conn.cursor()
        if not allow_duplicate:
            c.execute(
                "SELECT id, status FROM tasks WHERE keyword = ? AND status != 'skipped' AND status != 'rejected'",
                (keyword,))
            existing = c.fetchone()
            if existing:
                print(f"  Duplicate: '{keyword}' already exists as #{existing[0]} ({existing[1]})")
                return existing[0]
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

        # Always track status transition time in meta_json
        c.execute("SELECT meta_json FROM tasks WHERE id=?", (task_id,))
        row = c.fetchone()
        existing = json.loads(row[0]) if row and row[0] else {}
        existing["status_changed_at"] = now
        if meta:
            existing.update(meta)
        c.execute("UPDATE tasks SET meta_json=? WHERE id=?",
                  (json.dumps(existing, ensure_ascii=False), task_id))

        self.conn.commit()

    def save_stage_output(self, task_id: int, field: str, value: str):
        """Save research_note, outline, article, cascade outputs, or meta to a task."""
        allowed = {"research_note", "outline", "article", "article_html",
                   "title", "meta_description",
                   "synthesis", "framework", "prosody", "compiled_prompt"}
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

    def get_stuck_tasks(self, max_minutes: int = 30) -> list[dict]:
        """Find tasks stuck in non-terminal states for longer than max_minutes."""
        active_states = ("researching", "outlining", "writing", "outline_review")
        placeholders = ",".join(["?"] * len(active_states))
        c = self.conn.cursor()
        c.execute(
            f"SELECT * FROM tasks WHERE status IN ({placeholders}) "
            "ORDER BY priority ASC, created_at ASC",
            active_states
        )
        candidates = [dict(r) for r in c.fetchall()]
        cutoff = datetime.now(timezone.utc).timestamp() - max_minutes * 60

        stuck = []
        for t in candidates:
            meta = json.loads(t.get("meta_json") or "{}")
            changed_at_str = meta.get("status_changed_at")
            if not changed_at_str:
                # No transition recorded — use created_at as fallback
                changed_at_str = t.get("created_at", "")
            try:
                changed_ts = datetime.fromisoformat(changed_at_str.replace("Z", "+00:00")).timestamp()
            except (ValueError, TypeError):
                continue
            if changed_ts < cutoff:
                t["stuck_since"] = changed_at_str
                stuck.append(t)
        return stuck

    def recover_stuck(self, max_minutes: int = 30) -> list[dict]:
        """Roll back stuck tasks to their last stable state. Returns recovery report."""
        stuck = self.get_stuck_tasks(max_minutes)
        if not stuck:
            return []

        recovered = []
        for task in stuck:
            tid = task["id"]
            status = task["status"]
            has_research = bool(task.get("research_note"))
            has_outline = bool(task.get("outline"))

            if status in ("researching",) or (status == "outlining" and not has_research):
                rollback_to = "queued"
            elif status in ("outlining", "outline_review") and has_research:
                rollback_to = "researching"
            elif status == "writing" and has_outline:
                rollback_to = "outlining"
            elif status == "writing" and has_research:
                rollback_to = "researching"
            else:
                rollback_to = "queued"

            self.update_status(tid, rollback_to,
                               {"recovered_from": status,
                                "recovered_at": datetime.now(timezone.utc).isoformat()})
            recovered.append({
                "id": tid, "keyword": task["keyword"],
                "was": status, "rolled_back_to": rollback_to,
            })
        return recovered

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


def init_db(db_path: str = "~/docs/ai-context/article-pipeline-v1.db") -> TaskDB:
    """Initialize and return a TaskDB instance."""
    return TaskDB(db_path=db_path)
