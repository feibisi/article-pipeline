"""SQLite database layer for article pipeline task queue."""
import json
import os
import sqlite3
from datetime import datetime, timezone


def _expand_path(path: str) -> str:
    """Expand ~ in path."""
    return os.path.expanduser(path)


def normalize_keyword(keyword: str) -> str:
    """Normalize a keyword for duplicate detection.

    Collapses whitespace, lowercases ASCII, and folds full-width punctuation
    so that "systemd timer 基础" and "Systemd  Timer 基础" are the same topic.
    """
    if not keyword:
        return ""
    s = keyword.strip().lower()
    # Fold common full-width / decorative punctuation to a single space
    for ch in "：:，,。.、；;！!？?（）()【】[]「」《》\"'“”‘’-_—~·/\\|":
        s = s.replace(ch, " ")
    return " ".join(s.split())


# ── Status vocabulary (single source of truth) ──
# Terminal states: nothing will move them without human action.
TERMINAL_STATES = ("done", "published", "skipped", "rejected")
# States where a human is deliberately holding the task — never auto-recover.
HUMAN_GATE_STATES = ("outline_review", "reviewing")
# States owned by an automated stage; if nothing touches them they are stuck.
# Order matters: it is the cascade order, used by Pipeline.resume().
ACTIVE_STATES = (
    "researching", "synthesizing", "framework", "prosody",
    "compiling", "outlining", "writing",
)
# Max times recover_stuck() will requeue the same task before giving up.
# Without this a permanently-broken task ping-pongs between queued and stuck
# forever, burning API budget on every cycle.
MAX_RECOVERY_ATTEMPTS = 3


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

    def find_duplicate(self, keyword: str,
                       include_terminal: bool = False) -> dict | None:
        """Find an existing task covering the same topic.

        Matching is done on the normalized keyword so trivial variations
        (case, spacing, full-width punctuation) still count as duplicates.
        By default rejected/skipped topics are ignored so a failed topic can
        be retried; pass include_terminal=True to also surface published ones.
        """
        target = normalize_keyword(keyword)
        if not target:
            return None
        c = self.conn.cursor()
        c.execute("SELECT id, keyword, status FROM tasks ORDER BY id ASC")
        for row in c.fetchall():
            status = row["status"]
            if not include_terminal and status in ("skipped", "rejected"):
                continue
            if normalize_keyword(row["keyword"]) == target:
                return {"id": row["id"], "keyword": row["keyword"],
                        "status": status}
        return None

    def add_task(self, keyword: str, category: str = "wp-tech",
                 platform: str = "wptea", priority: int = 2,
                 allow_duplicate: bool = False) -> int | None:
        c = self.conn.cursor()
        if not allow_duplicate:
            existing = self.find_duplicate(keyword)
            if existing:
                print(f"  Duplicate: '{keyword}' already exists as "
                      f"#{existing['id']} ({existing['status']}) — "
                      f"'{existing['keyword']}'")
                return existing["id"]
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

        # Promote known real columns out of the meta blob so that
        # published_url / skip_reason land in their actual columns, not only
        # in meta_json (previously they were silently swallowed by the blob,
        # leaving `done` tasks with an empty published_url column).
        if meta:
            for col in ("published_url", "skip_reason"):
                if col in meta and meta[col] is not None:
                    fields += f", {col}=?"
                    params.append(meta[col])

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

    def save_meta(self, task_id: int, meta: dict):
        """Merge keys into a task's meta_json blob.

        Previously missing entirely — pipeline.process_compile() and
        screenshot.py called it and died with AttributeError, which aborted
        every cascade run at the compile stage.
        """
        c = self.conn.cursor()
        c.execute("SELECT meta_json FROM tasks WHERE id=?", (task_id,))
        row = c.fetchone()
        if row is None:
            raise ValueError(f"Task #{task_id} not found")
        try:
            existing = json.loads(row[0]) if row[0] else {}
        except (json.JSONDecodeError, TypeError):
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        existing.update(meta or {})
        c.execute("UPDATE tasks SET meta_json=? WHERE id=?",
                  (json.dumps(existing, ensure_ascii=False), task_id))
        self.conn.commit()
        return existing

    def peek_next_batch(self, limit: int = 5, category: str | None = None,
                        max_priority: int | None = None) -> list[dict]:
        """Return the next N queued tasks WITHOUT claiming them (for dry-run)."""
        query = "SELECT * FROM tasks WHERE status='queued'"
        params: list = []
        if category:
            query += " AND category=?"
            params.append(category)
        if max_priority is not None:
            query += " AND priority<=?"
            params.append(max_priority)
        query += " ORDER BY priority ASC, created_at ASC LIMIT ?"
        params.append(limit)
        c = self.conn.cursor()
        c.execute(query, params)
        return [dict(r) for r in c.fetchall()]

    def get_next_batch(self, limit: int = 5, category: str | None = None,
                       max_priority: int | None = None) -> list[dict]:
        """Claim next N queued tasks, set them to researching, return them.

        Claiming mutates state — use peek_next_batch() for previews.
        """
        rows = self.peek_next_batch(limit=limit, category=category,
                                    max_priority=max_priority)
        for r in rows:
            self.update_status(r["id"], "researching")
            r["status"] = "researching"
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

    @staticmethod
    def _parse_ts(value: str | None) -> float | None:
        """Parse either an ISO-8601 or a 'YYYY-MM-DD HH:MM:SS' timestamp (UTC)."""
        if not value:
            return None
        raw = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except (ValueError, TypeError):
            return None
        if dt.tzinfo is None:
            # DB writes naive UTC strings (datetime('now') / strftime above)
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    def get_stuck_tasks(self, max_minutes: int = 30,
                        include_human_gates: bool = False) -> list[dict]:
        """Find tasks idle in an automated state for longer than max_minutes.

        Covers the whole cascade (researching → writing). Human gate states
        (outline_review / reviewing) are excluded by default: a human sitting
        on a task is not a fault, and auto-rewinding those states destroys
        work that is waiting for approval.
        """
        states = list(ACTIVE_STATES)
        if include_human_gates:
            states += list(HUMAN_GATE_STATES)
        placeholders = ",".join(["?"] * len(states))
        c = self.conn.cursor()
        c.execute(
            f"SELECT * FROM tasks WHERE status IN ({placeholders}) "
            "ORDER BY priority ASC, created_at ASC",
            states
        )
        candidates = [dict(r) for r in c.fetchall()]
        cutoff = datetime.now(timezone.utc).timestamp() - max_minutes * 60

        stuck = []
        for t in candidates:
            try:
                meta = json.loads(t.get("meta_json") or "{}")
            except (json.JSONDecodeError, TypeError):
                meta = {}
            changed_at_str = meta.get("status_changed_at") or t.get("created_at")
            changed_ts = self._parse_ts(changed_at_str)
            if changed_ts is None:
                # Unparseable/absent timestamp must not hide a stuck task.
                t["stuck_since"] = changed_at_str or "unknown"
                t["stuck_minutes"] = None
                stuck.append(t)
                continue
            if changed_ts < cutoff:
                t["stuck_since"] = changed_at_str
                t["stuck_minutes"] = int(
                    (datetime.now(timezone.utc).timestamp() - changed_ts) / 60)
                stuck.append(t)
        return stuck

    def recover_stuck(self, max_minutes: int = 30,
                      include_human_gates: bool = False) -> list[dict]:
        """Requeue stalled tasks so `run` picks them up again.

        Everything goes back to 'queued' — the only status run() claims.
        The old implementation rewound to intermediate states like
        'researching'/'outlining', which run() never selects, so "recovered"
        tasks stayed dead until someone noticed and ran `continue` by hand.

        Stage outputs are kept: the cascade overwrites each column as it
        recomputes it, so requeueing is idempotent. After
        MAX_RECOVERY_ATTEMPTS the task is skipped instead of looping forever.
        """
        stuck = self.get_stuck_tasks(max_minutes,
                                     include_human_gates=include_human_gates)
        if not stuck:
            return []

        recovered = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for task in stuck:
            tid = task["id"]
            status = task["status"]
            try:
                meta = json.loads(task.get("meta_json") or "{}")
            except (json.JSONDecodeError, TypeError):
                meta = {}
            attempts = int(meta.get("recovery_attempts", 0)) + 1

            if attempts > MAX_RECOVERY_ATTEMPTS:
                self.update_status(tid, "skipped", {
                    "recovery_attempts": attempts,
                    "recovered_from": status,
                    "recovered_at": now_iso,
                    "skip_reason": (
                        f"recovery_exhausted: stalled at '{status}' after "
                        f"{MAX_RECOVERY_ATTEMPTS} requeues"),
                })
                recovered.append({
                    "id": tid, "keyword": task["keyword"], "was": status,
                    "rolled_back_to": "skipped", "attempts": attempts,
                })
                continue

            self.update_status(tid, "queued", {
                "recovered_from": status,
                "recovered_at": now_iso,
                "recovery_attempts": attempts,
            })
            recovered.append({
                "id": tid, "keyword": task["keyword"], "was": status,
                "rolled_back_to": "queued", "attempts": attempts,
            })
        return recovered

    def record_failure(self, task_id: int, stage: str, error: str,
                       traceback_text: str = "") -> dict:
        """Append a structured failure record to the task's error_log.

        Gives an operator an answer to "where did last night's run die?"
        without grepping stdout that nobody captured.
        """
        entry = {
            "stage": stage,
            "error": str(error)[:1000],
            "at": datetime.now(timezone.utc).isoformat(),
        }
        if traceback_text:
            entry["traceback"] = traceback_text[-2000:]
        c = self.conn.cursor()
        c.execute("SELECT meta_json FROM tasks WHERE id=?", (task_id,))
        row = c.fetchone()
        try:
            meta = json.loads(row[0]) if row and row[0] else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}
        log = meta.setdefault("error_log", [])
        log.append(entry)
        meta["error_log"] = log[-20:]
        meta["last_error"] = entry
        c.execute("UPDATE tasks SET meta_json=? WHERE id=?",
                  (json.dumps(meta, ensure_ascii=False), task_id))
        self.conn.commit()
        return entry

    def status_counts(self) -> dict:
        """status -> count, for monitoring/observability."""
        c = self.conn.cursor()
        c.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status")
        return {r[0]: r[1] for r in c.fetchall()}

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
