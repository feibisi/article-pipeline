"""Pipeline orchestrator — ties together all stages of article production."""
import os
import json
import yaml
from datetime import datetime, timezone
from pathlib import Path
from article_pipeline.db import TaskDB
from article_pipeline.research import gather_research, build_research_note
from article_pipeline.outline import generate_outline, format_outline_for_review
from article_pipeline.writer import write_article, write_article_claude
from article_pipeline.review import run_self_review
from article_pipeline.publish import publish_to_wp

RUNS_DIR = Path.home() / "workspaces" / "article-pipeline" / "runs"


def _write_run(task_id: str, workspace: str, status: str,
               outputs: list[dict] | None = None,
               issues: list[dict] | None = None,
               next_step: str = ""):
    """Write a standardized run report per TASKS.md protocol."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    run = {
        "task_id": task_id,
        "workspace": workspace,
        "status": status,
        "started_at": now,
        "finished_at": now,
        "outputs": outputs or [],
        "issues": issues or [],
        "next": next_step,
    }
    fname = RUNS_DIR / f"{task_id}.json"
    fname.write_text(json.dumps(run, ensure_ascii=False, indent=2))


def _load_config():
    config_path = os.path.expanduser("~/.config/article-pipeline/config.yaml")
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
            return config if isinstance(config, dict) else {}
    except (FileNotFoundError, yaml.YAMLError):
        return {}


class Pipeline:
    """Article production pipeline orchestrator."""

    def __init__(self, db: TaskDB | None = None):
        self.db = db or TaskDB()
        self.config = _load_config()

    def run(self, limit: int = 5):
        """Process next batch of queued tasks through the pipeline."""
        batch = self.db.get_next_batch(limit=limit)
        if not batch:
            print("No queued tasks found.")
            return []

        results = []
        for task in batch:
            tid = task["id"]
            print(f"\n{'='*60}")
            print(f"Processing #{tid}: {task['keyword']} [{task['category']}]")

            try:
                r = self.process_research(tid)
                if r:
                    results.append(r)
                    r = self.process_outline(tid)
                    if r:
                        results.append(r)
                        r = self.process_writing(tid)
                        if r:
                            results.append(r)
                            r = self.process_review(tid)
                            if r:
                                results.append(r)
            except Exception as e:
                print(f"  FAILED: {e}")
                self.db.update_status(tid, "skipped",
                                      {"skip_reason": f"pipeline_error: {e}"})

        return results

    def resume(self, task_id: int):
        """Resume a task from its current status."""
        task = self.db.get_task(task_id)
        if not task:
            print(f"Task #{task_id} not found.")
            return

        status = task["status"]
        print(f"Resuming #{task_id} from status: {status}")

        try:
            if status in ("researching", "outlining"):
                r = self.process_research(task_id)
                if r:
                    r = self.process_outline(task_id)
                    if r:
                        r = self.process_writing(task_id)
                        if r:
                            self.process_review(task_id)
            elif status == "writing":
                r = self.process_writing(task_id)
                if r:
                    self.process_review(task_id)
            elif status == "reviewing":
                print("Already in review. Use: article-pipeline review")
            else:
                print(f"Status '{status}' not resumable.")
        except Exception as e:
            print(f"  FAILED: {e}")
            self.db.update_status(task_id, "skipped",
                                  {"skip_reason": f"resume_error: {e}"})

    def process_research(self, task_id: int) -> dict | None:
        """Stage 2: Gather research for a task."""
        task = self.db.get_task(task_id)
        print(f"  [research] Gathering materials...")

        sources = gather_research(task["keyword"], task["category"])
        note = build_research_note(task["keyword"], sources)

        self.db.save_stage_output(task_id, "research_note", note)
        self.db.update_status(task_id, "outlining")
        print(f"  [research] Done — {len(note)} chars, "
              f"{len(sources.get('cocobook', []))} book results")

        return {"task_id": task_id, "stage": "research", "note_length": len(note)}

    def process_outline(self, task_id: int) -> dict | None:
        """Stage 3: Generate outline from research."""
        task = self.db.get_task(task_id)
        print(f"  [outline] Generating...")

        outline = generate_outline(
            task["keyword"], task["category"], task["platform"],
            task["research_note"] or ""
        )

        if "error" in outline:
            print(f"  [outline] FAILED: {outline['error']}")
            # Retry up to 2 times before skipping
            import json as _j
            meta = _j.loads(task.get("meta_json", "{}") or "{}")
            retries = meta.get("outline_retries", 0)
            if retries < 2:
                meta["outline_retries"] = retries + 1
                self.db.update_status(task_id, "outlining", meta)
                print(f"  [outline] Will retry ({retries + 1}/2)")
            else:
                self.db.update_status(task_id, "skipped",
                                      {"skip_reason": f"outline_failed: {outline['error']}"})
            return None

        # Save outline as JSON
        outline_json = json.dumps(outline, ensure_ascii=False, indent=2)
        self.db.save_stage_output(task_id, "outline", outline_json)

        # Save title from first candidate
        if outline.get("titles") and len(outline["titles"]) > 0:
            self.db.save_stage_output(task_id, "title",
                                       outline["titles"][0].get("text", task.get("keyword", "")))

        # Save meta description
        seo = outline.get("seo", {})
        if seo.get("meta_description"):
            self.db.save_stage_output(task_id, "meta_description",
                                       seo["meta_description"])

        self.db.update_status(task_id, "writing")
        print(f"  [outline] Done — {len(outline.get('sections', []))} sections")

        return {"task_id": task_id, "stage": "outline"}

    def process_writing(self, task_id: int) -> dict | None:
        """Stage 4: Write full article."""
        task = self.db.get_task(task_id)
        print(f"  [writing] Generating article...")

        outline = json.loads(task["outline"] or "{}")
        research_note = task["research_note"] or ""

        if task["category"] == "book-knowledge":
            result = write_article_claude(
                task["keyword"], task["category"], outline, research_note
            )
        else:
            result = write_article(
                task["keyword"], task["category"], outline, research_note
            )

        if "error" in result:
            print(f"  [writing] FAILED: {result['error']}")
            meta = json.loads(task.get("meta_json", "{}") or "{}")
            retries = meta.get("writing_retries", 0)
            if retries < 2:
                meta["writing_retries"] = retries + 1
                self.db.update_status(task_id, "writing", meta)
                print(f"  [writing] Will retry ({retries + 1}/2)")
            else:
                self.db.update_status(task_id, "skipped",
                                      {"skip_reason": f"writing_failed: {result['error']}"})
            return None

        self.db.save_stage_output(task_id, "article", result["article"])
        self.db.update_status(task_id, "reviewing")
        print(f"  [writing] Done — model: {result.get('model', 'unknown')}")

        _write_run(f"write-{task_id}", "article-pipeline", "completed",
                    outputs=[{"type": "db", "table": "tasks", "field": "article",
                              "chars": len(result["article"])}],
                    next_step="review")
        return {"task_id": task_id, "stage": "writing"}

    def process_review(self, task_id: int) -> dict:
        """Stage 5: Self-review article."""
        task = self.db.get_task(task_id)
        print(f"  [review] Running checks...")

        results = run_self_review(
            task["article"] or "",
            tier="A",
            research_note=task["research_note"] or ""
        )

        self.db.add_review_entry(task_id, results,
                                 passed=results.get("overall_pass", False))

        if results.get("overall_pass"):
            status = "PASS"
        else:
            status = "FLAGGED"

        print(f"  [review] {status} — AI score: "
              f"{results.get('ai_check', {}).get('score', '?')}")

        _write_run(f"review-{task_id}", "article-pipeline",
                    "completed" if results.get("overall_pass") else "partial",
                    outputs=[{"type": "db", "table": "review_log",
                              "score": results.get("overall_score", 0)}],
                    next_step="human_review" if results.get("overall_pass") else "human_review_or_revise")
        return results

    def show_review_queue(self):
        """Display articles ready for human review (status=reviewing)."""
        tasks = self.db.list_tasks(status="reviewing")
        if not tasks:
            print("No articles awaiting review.")
            return

        for task in tasks:
            print(f"\n{'='*60}")
            print(f"#{task['id']} | {task['category']} | {task['keyword']}")
            print(f"Title: {task.get('title', 'N/A')}")
            print(f"Meta: {task.get('meta_description', 'N/A')}")

            article = task.get("article", "")
            if article:
                preview = article[:300].replace("\n", " ")
                print(f"\nPreview: {preview}...")
                print(f"\nFull length: {len(article)} chars")

            # Show review results
            c = self.db.conn.cursor()
            c.execute(
                "SELECT * FROM review_log WHERE task_id=? ORDER BY id DESC LIMIT 1",
                (task["id"],)
            )
            review = c.fetchone()
            if review:
                import json as jmod
                checks = jmod.loads(review["check_results"])
                ai = checks.get("ai_check", {})
                wc = checks.get("word_count", {})
                print(f"\nSelf-review: {'PASS' if review['passed'] else 'FLAGGED'}")
                print(f"  AI score: {ai.get('score', '?')}/10 "
                      f"(flags: {len(ai.get('flags', []))})")
                print(f"  Word count: {wc.get('chars', '?')} chars")

            print(f"\n  Commands:")
            print(f"  article-pipeline publish {task['id']}   # approve and publish")
            print(f"  article-pipeline skip {task['id']} --reason '...'  # reject")

    def publish(self, task_id: int):
        """Publish an approved article to WordPress."""
        task = self.db.get_task(task_id)
        if not task:
            print(f"Task #{task_id} not found.")
            return

        if task["status"] != "reviewing":
            print(f"Task #{task_id} is not in reviewing status "
                  f"(current: {task['status']})")
            return

        title = task.get("title") or task["keyword"]
        article = task.get("article", "")
        meta_desc = task.get("meta_description", "")

        print(f"Publishing #{task_id}: {title}")
        result = publish_to_wp(task_id, title, article, meta_desc, task["platform"])

        if "error" in result:
            print(f"  FAILED: {result['error']}")
            return

        self.db.update_status(task_id, "done",
                              {"published_url": result.get("url", "")})
        print(f"  Published: {result.get('url', 'unknown')}")
