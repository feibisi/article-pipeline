"""Pipeline orchestrator — ties together all stages of article production.

Cascade architecture: research → synthesis → framework → style → prosody → compile → write → review → publish
"""
from article_pipeline.config import load_config
from article_pipeline.text_utils import fix_em_dashes
import os
import json
import yaml
from datetime import datetime, timezone
from pathlib import Path
from article_pipeline.db import (
    TaskDB, TERMINAL_STATES, HUMAN_GATE_STATES, ACTIVE_STATES,
)
from article_pipeline.research import gather_research, build_research_note
from article_pipeline.synthesis import run_synthesis
from article_pipeline.framework import run_framework
from article_pipeline.prosody import run_prosody
from article_pipeline.compile import run_compile
from article_pipeline.outline import generate_outline, format_outline_for_review
from article_pipeline.writer import write_article, write_article_claude, get_trust_tier
from article_pipeline.review import run_self_review, compute_publish_gate
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



class Pipeline:
    """Article production pipeline orchestrator."""

    # status -> the method that owns that stage. Single source of truth for
    # the cascade order; anything not listed here is a gate or terminal state.
    STAGE_METHODS = {
        "researching": "process_research",
        "synthesizing": "process_synthesis",
        "framework": "process_framework",
        "prosody": "process_prosody",
        "compiling": "process_compile",
        "outlining": "process_outline",
        "writing": "process_writing",
    }

    def __init__(self, db: TaskDB | None = None):
        self.db = db or TaskDB()
        self.config = load_config()

    # ── Stage driver ──

    def _drive(self, task_id: int, max_steps: int = 24) -> list[dict]:
        """Advance one task as far as it can go, one stage at a time.

        Replaces the old deeply-nested if-chain in run(), which
        (a) mis-indented the outline branch so a TIER_EXTERNAL task that
        stopped at the human gate was written anyway, and (b) gave no way to
        tell which stage failed. Driving off the DB status instead of a
        hardcoded chain means resume/recover use the exact same path as run.
        """
        results: list[dict] = []
        for _ in range(max_steps):
            task = self.db.get_task(task_id)
            if not task:
                print(f"  Task #{task_id} disappeared.")
                break
            status = task["status"]

            if status in TERMINAL_STATES:
                print(f"  [{status}] terminal — stopping.")
                break
            if status == "outline_review":
                print(f"  [gate] Outline awaits approval: "
                      f"ap approve-outline {task_id}")
                break
            if status == "reviewing":
                # Human gate. Self-review runs once, then we hand over.
                if any(r.get("stage") == "review" for r in results):
                    break
                try:
                    r = self.process_review(task_id)
                except Exception as e:
                    self._record_stage_failure(task_id, "review", e)
                    break
                results.append({"task_id": task_id, "stage": "review",
                                "passed": bool(r.get("overall_pass"))})
                print(f"  [gate] Awaiting human review: ap review-queue")
                break
            if status == "queued":
                self.db.update_status(task_id, "researching")
                continue

            method = self.STAGE_METHODS.get(status)
            if method is None:
                self._record_stage_failure(
                    task_id, status,
                    f"unknown status '{status}' — no stage owns it")
                break

            try:
                r = getattr(self, method)(task_id)
            except Exception as e:
                self._record_stage_failure(task_id, status, e)
                break

            if r is None:
                # Stage deliberately stopped (skipped, or requeued for retry).
                after = self.db.get_task(task_id)
                print(f"  [{status}] stopped — task now "
                      f"'{after['status'] if after else '?'}'")
                break

            results.append(r)

            after = self.db.get_task(task_id)
            if after and after["status"] == status:
                # A stage that returns success must advance the status,
                # otherwise we would spin here forever.
                self._record_stage_failure(
                    task_id, status,
                    f"stage '{method}' returned success without leaving "
                    f"status '{status}'")
                break
        else:
            self._record_stage_failure(
                task_id, "driver", f"exceeded {max_steps} stage transitions")
        return results

    def _record_stage_failure(self, task_id: int, stage: str, error) -> None:
        """Mark a task failed at a named stage, with a durable audit record."""
        import traceback
        tb = traceback.format_exc() if isinstance(error, BaseException) else ""
        print(f"  [{stage}] FAILED: {error}")
        self.db.record_failure(task_id, stage, str(error), tb)
        self.db.update_status(task_id, "skipped", {
            "skip_reason": f"{stage}_error: {error}",
            "failed_stage": stage,
        })
        _write_run(f"{stage}-{task_id}", "article-pipeline", "failed",
                   issues=[{"stage": stage, "error": str(error)[:500]}],
                   next_step=f"inspect: ap status {task_id}")

    def run(self, limit: int = 5, category: str | None = None,
            max_priority: int | None = None):
        """Process next batch of queued tasks through the pipeline.

        NOTE: this claims tasks itself. Callers must not call
        get_next_batch() first — that double-claims and skips tasks.
        """
        batch = self.db.get_next_batch(limit=limit, category=category,
                                       max_priority=max_priority)
        if not batch:
            print("No queued tasks found.")
            return []

        results = []
        for task in batch:
            tid = task["id"]
            print(f"\n{'='*60}")
            print(f"Processing #{tid}: {task['keyword']} [{task['category']}]")
            results.extend(self._drive(tid))

        return results

    def resume(self, task_id: int):
        """Resume a task from its current status.

        Every automated state is resumable now. Previously anything in
        synthesizing/framework/prosody/compiling hit "not resumable" and
        could only be freed by hand-editing SQLite.
        """
        task = self.db.get_task(task_id)
        if not task:
            print(f"Task #{task_id} not found.")
            return []

        status = task["status"]
        if status in TERMINAL_STATES:
            print(f"Task #{task_id} is {status} — nothing to resume.")
            return []
        if status == "outline_review":
            print(f"Task #{task_id} needs outline approval: "
                  f"ap approve-outline {task_id}")
            return []
        if status == "reviewing":
            print(f"Task #{task_id} already written and self-reviewed. "
                  f"Use: ap review-queue / ap publish {task_id}")
            return []

        print(f"Resuming #{task_id} from status: {status}")
        return self._drive(task_id)

    def approve_outline(self, task_id: int):
        """Approve a TIER_EXTERNAL outline and proceed to writing."""
        task = self.db.get_task(task_id)
        if not task:
            print(f"Task #{task_id} not found.")
            return
        if task["status"] != "outline_review":
            print(f"Task #{task_id} is not awaiting outline review (current: {task['status']}).")
            return
        self.db.update_status(task_id, "writing",
                              {"outline_approved_at":
                               datetime.now(timezone.utc).isoformat()})
        print(f"Outline approved for #{task_id}. Proceeding to writing...")
        return self._drive(task_id)

    def process_research(self, task_id: int) -> dict | None:
        """Stage 2: Gather research for a task."""
        task = self.db.get_task(task_id)
        print(f"  [research] Gathering materials...")

        sources = gather_research(task["keyword"], task["category"])
        note = build_research_note(task["keyword"], sources)

        self.db.save_stage_output(task_id, "research_note", note)
        # Save sources for synthesis layer (in meta_json)
        sources_json = json.dumps({
            "annotations": sources.get("annotations", [])[:10],
            "ddg_results": sources.get("web", [])[:10],
            "web_articles": sources.get("web_articles", [])[:5],
            "topic_paragraphs": sources.get("topic_paragraphs", [])[:10],
        }, ensure_ascii=False)
        self.db.conn.execute(
            "UPDATE tasks SET meta_json=? WHERE id=?",
            (sources_json, task_id)
        )
        self.db.conn.commit()
        self.db.update_status(task_id, "synthesizing")
        print(f"  [research] Done — {len(note)} chars, "
              f"{len(sources.get('cocobook', []))} book results")

        return {"task_id": task_id, "stage": "research", "note_length": len(note)}

    def process_synthesis(self, task_id: int) -> dict | None:
        """Stage 2.5: Synthesis layer — extract core judgment from research."""
        task = self.db.get_task(task_id)
        print(f"  [synthesis] Analyzing...")

        # Load sources from meta_json (saved by process_research)
        meta_json = task.get("meta_json", "{}")
        try:
            sources_data = json.loads(meta_json) if meta_json != "{}" else {}
        except json.JSONDecodeError:
            sources_data = {}

        sources = {
            "annotations": sources_data.get("annotations", []),
            "ddg_results": sources_data.get("ddg_results", []),
            "web_articles": sources_data.get("web_articles", []),
            "topic_paragraphs": sources_data.get("topic_paragraphs", []),
        }

        # keyword focuses the synthesis LLM; without it the cascade's root layer
        # summarises the material without knowing what the article is about.
        synthesis = run_synthesis(sources, keyword=task["keyword"])

        if not synthesis or not synthesis.core_judgment:
            print(f"  [synthesis] SKIPPED: No core judgment formed")
            self.db.update_status(task_id, "skipped",
                                  {"skip_reason": "synthesis_no_judgment"})
            return None

        # Save synthesis output
        synthesis_json = json.dumps({
            "core_judgment": synthesis.core_judgment,
            "evidence_for": synthesis.evidence_for,
            "evidence_against": synthesis.evidence_against,
            "conflicts": synthesis.conflicts,
            "unique_claims": synthesis.unique_claims,
            "differentiation": synthesis.differentiation,
            "confidence": synthesis.confidence,
            "freeform_note": synthesis.freeform_note,
        }, ensure_ascii=False)
        self.db.save_stage_output(task_id, "synthesis", synthesis_json)

        self.db.update_status(task_id, "framework")
        print(f"  [synthesis] Done — judgment: {synthesis.core_judgment[:50]}...")
        print(f"  [synthesis] Confidence: {synthesis.confidence:.2f}")

        return {"task_id": task_id, "stage": "synthesis", "confidence": synthesis.confidence}

    def process_framework(self, task_id: int) -> dict | None:
        """Stage 3: Framework layer — build methodology-driven structure."""
        task = self.db.get_task(task_id)
        print(f"  [framework] Building structure...")

        # Load synthesis output through the typed contract.
        # Hand-rolling `SynthesisOutput(core_judgment=d.get("core_judgment",""))`
        # meant an empty/corrupt synthesis column produced a valid-looking
        # object with no core judgment, and the cascade happily wrote an
        # article about nothing. from_dict() raises instead.
        from article_pipeline.contracts import SynthesisOutput
        import json as _j
        synthesis_data = _j.loads(task.get("synthesis") or "{}")
        synthesis = SynthesisOutput.from_dict(synthesis_data)

        # Get genre from category (simplified mapping)
        genre = self._map_category_to_genre(task["category"])

        framework = run_framework(synthesis, genre)

        # Save framework output
        framework_json = json.dumps({
            "method": framework.method,
            "structure": framework.structure,
            "takeaway": framework.takeaway,
            "reader_entry_state": framework.reader_entry_state,
            "reader_exit_state": framework.reader_exit_state,
            "visual_anchors": framework.visual_anchors,
            "freeform_note": framework.freeform_note,
        }, ensure_ascii=False)
        self.db.save_stage_output(task_id, "framework", framework_json)

        self.db.update_status(task_id, "prosody")
        print(f"  [framework] Done — method: {framework.method}, sections: {len(framework.structure)}")

        return {"task_id": task_id, "stage": "framework", "method": framework.method}

    def _map_category_to_genre(self, category: str) -> str:
        """Map pipeline category to genre identifier."""
        # Simplified mapping
        mapping = {
            "tutorial": "tutorial",
            "guide": "guide",
            "comparison": "comparison",
            "opinion": "opinion",
            "troubleshooting": "troubleshooting",
            "case-study": "case_study",
            "beginner": "beginner",
            "tool-review": "tool_review",
        }
        return mapping.get(category.lower(), "tutorial")

    def process_prosody(self, task_id: int) -> dict | None:
        """Stage 4: Prosody layer — inject rhythm and style samples."""
        task = self.db.get_task(task_id)
        print(f"  [prosody] Loading samples...")

        # Load style preset for genre
        from article_pipeline.style import get_preset_dict
        genre = self._map_category_to_genre(task["category"])
        style_dict = get_preset_dict(genre)

        # Convert dict to StyleOutput-like structure
        from article_pipeline.contracts import StyleOutput
        style_output = StyleOutput(
            vector=style_dict,
            constraints={},  # Constraints not in style vector, use genre rules
            rendered_instructions="",
            aesthetic_concepts=[],
        )

        prosody = run_prosody(style_output, genre)

        # Save prosody output
        prosody_json = json.dumps({
            "sample_type": prosody.sample_type,
            "samples": prosody.samples,
            "negative_constraints": prosody.negative_constraints,
            "rhythm_hint": prosody.rhythm_hint,
            "freeform_note": prosody.freeform_note,
        }, ensure_ascii=False)
        self.db.save_stage_output(task_id, "prosody", prosody_json)

        self.db.update_status(task_id, "compiling")
        print(f"  [prosody] Done — type: {prosody.sample_type}, samples: {len(prosody.samples)}")

        return {"task_id": task_id, "stage": "prosody", "sample_type": prosody.sample_type}

    def process_compile(self, task_id: int) -> dict | None:
        """Stage 5: Compile layer — assemble final writer prompt."""
        task = self.db.get_task(task_id)
        print(f"  [compile] Assembling prompt...")

        # Load all layer outputs
        import json as _j
        framework_data = _j.loads(task.get("framework", "{}"))
        prosody_data = _j.loads(task.get("prosody", "{}"))

        # Reconstruct data objects through the typed contracts (see
        # process_framework for why the hand-rolled .get() version was unsafe).
        from article_pipeline.contracts import FrameworkOutput, ProsodyOutput, StyleOutput
        framework = FrameworkOutput.from_dict(framework_data)
        prosody = ProsodyOutput.from_dict(prosody_data)

        # Phase 4: Get style preset and generate dynamic rules
        from article_pipeline.style import get_preset, render_temperament
        from article_pipeline.style_phase4 import render_genre_rules
        genre = self._map_category_to_genre(task["category"])
        style_vector = get_preset(genre)
        style_dict = {
            "density": style_vector.density,
            "warmth": style_vector.warmth,
            "energy": style_vector.energy,
            "register": style_vector.register,
            "edge": style_vector.edge,
            "injection": style_vector.injection,
            "active": style_vector.active,
        }

        # Generate dynamic rules from style vector
        rules = render_genre_rules(task["category"])

        # Convert Phase 4 rules to constraints dict
        # Phase 4 规则都是正向要求，统一放入 require
        constraints = {"require": [], "avoid": []}
        for rule_type, rule_list in rules.items():
            if rule_type in ["sentence", "rhythm", "stance", "structure", "data"]:
                constraints["require"].extend(rule_list)

        # Add temperament description
        temperament_list = render_temperament(style_vector)
        temperament = "\n".join(temperament_list) if temperament_list else ""

        style = StyleOutput(
            vector=style_dict,
            constraints=constraints,
            rendered_instructions=temperament,
            aesthetic_concepts=[],
        )

        # Build material from synthesis
        synthesis_data = _j.loads(task.get("synthesis", "{}"))
        material = {
            "evidence_for": synthesis_data.get("evidence_for", []),
            "evidence_against": synthesis_data.get("evidence_against", []),
        }

        # Compile final prompt
        compile_output = run_compile(framework, style, prosody, material, task["keyword"], task["category"])

        # Save compiled prompt (markdown)
        self.db.save_stage_output(task_id, "compiled_prompt", compile_output.markdown)

        # Save structured metadata (JSON)
        compile_metadata = json.dumps({
            "hero_brief": {
                "concept": compile_output.hero_brief.concept if compile_output.hero_brief else None,
                "mood": compile_output.hero_brief.mood if compile_output.hero_brief else None,
                "dimensions": compile_output.hero_brief.dimensions if compile_output.hero_brief else None,
            } if compile_output.hero_brief else None,
            "visual_anchors": [
                {
                    "section_role": v.section_role,
                    "concept": v.concept,
                    "visual_type": v.visual_type,
                    "screenshot_target": v.screenshot_target,
                }
                for v in compile_output.visual_anchors
            ],
            "seo_metadata": {
                "title": compile_output.seo_metadata.title if compile_output.seo_metadata else None,
                "description": compile_output.seo_metadata.description if compile_output.seo_metadata else None,
                "excerpt": compile_output.seo_metadata.excerpt if compile_output.seo_metadata else None,
            } if compile_output.seo_metadata else None,
            "tags": compile_output.tags,
            "cta": compile_output.cta,
        }, ensure_ascii=False)
        self.db.save_meta(task_id, {"compile_metadata": compile_metadata})

        self.db.update_status(task_id, "outlining")
        print(f"  [compile] Done — prompt length: {len(compile_output.markdown)} chars, "
              f"{len(compile_output.visual_anchors)} visual anchors")

        return {"task_id": task_id, "stage": "compile", "prompt_length": len(compile_output.markdown)}

    def process_outline(self, task_id: int) -> dict | None:
        """Stage 5.5: Generate outline from layer outputs（Phase 2 改造版）.

        现在 outline 基于 synthesis + framework + style + prosody 的输出生成，
        而非从 research_note 直接生成。
        """
        task = self.db.get_task(task_id)
        print(f"  [outline] Generating from layers...")

        # Load all layer outputs
        import json as _j
        synthesis_data = _j.loads(task.get("synthesis", "{}"))
        framework_data = _j.loads(task.get("framework", "{}"))
        prosody_data = _j.loads(task.get("prosody", "{}"))

        # Build style output from preset
        from article_pipeline.style import get_preset_dict, render_temperament
        from article_pipeline.contracts import StyleOutput, ProsodyOutput
        genre = self._map_category_to_genre(task["category"])
        style_dict = get_preset_dict(genre)

        # Generate constraints from Phase 4 rules
        from article_pipeline.style_phase4 import render_genre_rules
        rules = render_genre_rules(task["category"])
        constraints = {"require": [], "avoid": []}
        for rule_type, rule_list in rules.items():
            if rule_type in ["sentence", "rhythm", "stance", "structure", "data"]:
                constraints["require"].extend(rule_list)

        style_vector_dict = {
            "density": style_dict.get("density", 0.0),
            "warmth": style_dict.get("warmth", 0.0),
            "energy": style_dict.get("energy", 0.0),
            "register": style_dict.get("register", 0.0),
            "edge": style_dict.get("edge", 0.0),
            "injection": style_dict.get("injection", "full"),
            "active": style_dict.get("active", True),
        }

        style_output = {
            "vector": style_vector_dict,
            "constraints": constraints,
            "rendered_instructions": "",
            "aesthetic_concepts": [],
        }

        prosody_output = {
            "samples": prosody_data.get("samples", []),
            "sample_type": prosody_data.get("sample_type", ""),
            "negative_constraints": prosody_data.get("negative_constraints", ""),
            "rhythm_hint": prosody_data.get("rhythm_hint", ""),
            "freeform_note": prosody_data.get("freeform_note", ""),
        }

        # Generate outline from layers
        from article_pipeline.outline import generate_outline_from_layers
        outline = generate_outline_from_layers(
            keyword=task["keyword"],
            category=task["category"],
            platform=task["platform"],
            synthesis_output=synthesis_data,
            framework_output=framework_data,
            style_output=style_output,
            prosody_output=prosody_output,
        )

        if "error" in outline:
            print(f"  [outline] FAILED: {outline['error']}")
            # Retry up to 2 times before skipping
            import json as _j
            meta = _j.loads(task.get("meta_json", "{}") or "{}")
            retries = meta.get("outline_retries", 0)
            if retries < 2:
                meta["outline_retries"] = retries + 1
                self.db.update_status(task_id, "queued", meta)
                print(f"  [outline] Will retry ({retries + 1}/2)")
            else:
                self.db.update_status(task_id, "skipped",
                                      {"skip_reason": f"outline_failed: {outline['error']}"})
            return None

        # Skip low-value topics flagged by the takeaway check
        takeaway = (outline.get("takeaway") or "").strip()
        if takeaway.startswith("SKIP:"):
            print(f"  [outline] SKIPPED: {takeaway}")
            self.db.update_status(task_id, "skipped", {"skip_reason": takeaway})
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

        # Determine trust tier and store in task metadata
        tier = get_trust_tier(task["category"])
        import json as _j
        meta = _j.loads(task.get("meta_json", "{}") or "{}")
        meta["trust_tier"] = tier
        self.db.conn.execute(
            "UPDATE tasks SET meta_json = ? WHERE id = ?",
            (_j.dumps(meta), task_id))
        self.db.conn.commit()

        # TIER_EXTERNAL: stop here for human outline review
        if tier == "TIER_EXTERNAL":
            self.db.update_status(task_id, "outline_review")
            print(f"  [outline] TIER_EXTERNAL — human gate. Outline saved, awaiting approval.")
            readable = format_outline_for_review(outline)
            print(f"\n{'='*60}")
            print(f"  HUMAN GATE — outline requires review before writing")
            print(f"  Task #{task_id}: {task['keyword']} [{task['category']}]")
            print(f"  Review the outline, then: article-pipeline approve-outline {task_id}")
            print(f"{'='*60}")
            return {"task_id": task_id, "stage": "outline", "status": "awaiting_human"}

        self.db.update_status(task_id, "writing")
        print(f"  [outline] Done — {len(outline.get('sections', []))} sections")

        return {"task_id": task_id, "stage": "outline"}

    def process_writing(self, task_id: int) -> dict | None:
        """Stage 4: Write full article."""
        task = self.db.get_task(task_id)
        print(f"  [writing] Generating article...")

        outline = json.loads(task["outline"] or "{}")
        research_note = task["research_note"] or ""

        meta = json.loads(task.get("meta_json", "{}") or "{}")
        tier = meta.get("trust_tier", "TIER_INTERNAL")
        # Pass platform through outline for tone control
        outline["platform"] = task.get("platform", "")
        style_overrides = meta.get("style_overrides")

        # Source-attributed evidence from the synthesis layer. Without this the
        # writer only ever saw the truncated raw research note, where claims are
        # detached from their sources.
        synthesis_data = json.loads(task.get("synthesis") or "{}")
        evidence = synthesis_data.get("evidence_for") or []

        if task["category"] == "book-knowledge":
            result = write_article_claude(
                task["keyword"], task["category"], outline, research_note, tier=tier,
                style_overrides=style_overrides, evidence=evidence
            )
        else:
            result = write_article(
                task["keyword"], task["category"], outline, research_note, tier=tier,
                style_overrides=style_overrides, evidence=evidence
            )

        if "error" in result:
            print(f"  [writing] FAILED: {result['error']}")
            meta = json.loads(task.get("meta_json", "{}") or "{}")
            retries = meta.get("writing_retries", 0)
            if retries < 2:
                meta["writing_retries"] = retries + 1
                self.db.update_status(task_id, "queued", meta)
                print(f"  [writing] Will retry ({retries + 1}/2)")
            else:
                self.db.update_status(task_id, "skipped",
                                      {"skip_reason": f"writing_failed: {result['error']}"})
            return None

        article = result["article"]

        article = fix_em_dashes(article)
        prev_dashes = result["article"].count("——")
        if prev_dashes > 3:
            print(f"  [post] Fixed {prev_dashes} → 3 em-dashes")

        # Stage 4b: Render Mermaid diagrams to SVG
        from article_pipeline.mermaid import render_article_diagrams, extract_mermaid_blocks
        mermaid_blocks = extract_mermaid_blocks(article)
        if mermaid_blocks:
            diagrams_dir = Path.home() / "workspaces" / "article-pipeline" / "diagrams"
            rendered = render_article_diagrams(article, diagrams_dir, task_id)
            if rendered:
                print(f"  [mermaid] Rendered {len(rendered)}/{len(mermaid_blocks)} diagrams")
                meta = json.loads(task.get("meta_json", "{}") or "{}")
                meta["diagrams"] = rendered
                self.db.conn.execute(
                    "UPDATE tasks SET meta_json = ? WHERE id = ?",
                    (json.dumps(meta), task_id))
                self.db.conn.commit()

        self.db.save_stage_output(task_id, "article", article)

        # Track API token usage
        tokens = result.get("tokens", {})
        if tokens:
            meta = json.loads(task.get("meta_json", "{}") or "{}")
            cost_log = meta.setdefault("cost_log", [])
            cost_log.append({
                "model": result.get("model", "unknown"),
                "input_tokens": tokens.get("input_tokens", 0),
                "output_tokens": tokens.get("output_tokens", 0),
                "stage": "writing",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            self.db.conn.execute(
                "UPDATE tasks SET meta_json = ? WHERE id = ?",
                (json.dumps(meta), task_id))
            self.db.conn.commit()
            total_in = sum(e.get("input_tokens", 0) for e in cost_log)
            total_out = sum(e.get("output_tokens", 0) for e in cost_log)
            print(f"  [cost] input={tokens.get('input_tokens', 0)}, "
                  f"output={tokens.get('output_tokens', 0)}, "
                  f"running_total={total_in+total_out}")

        self.db.update_status(task_id, "reviewing")
        print(f"  [writing] Done — model: {result.get('model', 'unknown')}")

        _write_run(f"write-{task_id}", "article-pipeline", "completed",
                    outputs=[{"type": "db", "table": "tasks", "field": "article",
                              "chars": len(article)}],
                    next_step="review")
        return {"task_id": task_id, "stage": "writing"}

    def process_review(self, task_id: int) -> dict:
        """Stage 5: Self-review article."""
        task = self.db.get_task(task_id)
        print(f"  [review] Running checks...")

        meta = json.loads(task.get("meta_json", "{}") or "{}")
        trust_tier = meta.get("trust_tier", "TIER_INTERNAL")

        # The publish gate weighs three signals: material density, whether the
        # piece has a stated differentiation, and whether it carries unique
        # claims. All three are already on the task (synthesis column + the
        # sources cached in meta_json by process_research) but used to be left
        # unset here, so `has_differentiation` and `has_unique_claims` were
        # permanently False and source_depth fell back to counting URLs in the
        # prose. That made vd >= 6.0 the only route past the gate — against a
        # practical ceiling of ~7.5 — i.e. the gate rejected essentially
        # everything, including human-written published articles.
        try:
            synthesis_data = json.loads(task.get("synthesis") or "{}")
        except (json.JSONDecodeError, TypeError):
            synthesis_data = {}

        research_output = {
            "unique_claims": synthesis_data.get("unique_claims", []),
            "evidence_for": synthesis_data.get("evidence_for", []),
            "annotations": meta.get("annotations", []),
            "topic_paragraphs": meta.get("topic_paragraphs", []),
            "web_articles": meta.get("web_articles", []),
        }

        results = run_self_review(
            task["article"] or "",
            tier="A",
            research_note=task["research_note"] or "",
            trust_tier=trust_tier,
            category=task.get("category", ""),
            ddg_results=meta.get("ddg_results", []),
            research_output=research_output,
            differentiation=synthesis_data.get("differentiation", ""),
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


    def unpublish(self, task_id: int):
        """Revert a published/done task back to reviewing for revision."""
        task = self.db.get_task(task_id)
        if not task:
            print(f"Task #{task_id} not found.")
            return
        if task["status"] not in ("done", "published"):
            print(f"Task #{task_id} is not published (current: {task['status']})")
            return
        # Note: this does NOT delete the WordPress post (requires WP REST API delete).
        # It reverts the pipeline status so the article can be revised and republished.
        self.db.update_status(task_id, "reviewing",
                              {"unpublished_at": datetime.now(timezone.utc).isoformat()})
        print(f"  Task #{task_id} reverted to reviewing. "
              f"WP post still exists — delete manually if needed: "
              f"{task.get('published_url', 'N/A')}")
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

    def publish(self, task_id: int, dry_run: bool = False, force: bool = False):
        """Publish an approved article to WordPress."""
        task = self.db.get_task(task_id)
        if not task:
            print(f"Task #{task_id} not found.")
            return

        if task["status"] != "reviewing" and not dry_run:
            print(f"Task #{task_id} is not in reviewing status "
                  f"(current: {task['status']})")
            return

        title = task.get("title") or task["keyword"]
        article = task.get("article", "")
        meta_desc = task.get("meta_description", "")

        if dry_run:
            result = publish_to_wp(task_id, title, article, meta_desc,
                                   task["platform"], dry_run=True)
            print(f"DRY RUN #{task_id}: {title}")
            print(f"  route            : {result['planned_route']}")
            print(f"  REST endpoint    : "
                  f"{'configured' if result['rest_endpoint_configured'] else 'MISSING'}")
            print(f"  REST credentials : "
                  f"{'present' if result['rest_credentials_present'] else 'MISSING (will use translate bridge)'}")
            print(f"  category         : {result['category']}"
                  f"{'  (adjusted from ' + str(result.get('category')) + ')' if result['category_adjusted'] else ''}")
            print(f"  excerpt          : {result['excerpt'][:80]}")
            print(f"  content          : {result['content_chars']} chars")
            print(f"  blocks           : {result['block_counts']}")
            if result.get("already_published"):
                print(f"  WARNING: already published at {result['already_published']} "
                      f"— publishing again creates a duplicate post")
            print("  (nothing was sent: no HTTP request, no ssh, no post created)")
            return

        print(f"Publishing #{task_id}: {title}")
        result = publish_to_wp(task_id, title, article, meta_desc,
                               task["platform"], force=force)

        if "error" in result:
            print(f"  FAILED: {result['error']}: {result.get('message', '')}")
            return

        self.db.update_status(task_id, "done",
                              {"published_url": result.get("url", "")})
        print(f"  Published: {result.get('url', 'unknown')}")

    def add_task(self, keyword: str, category: str = "wp-tech",
                 platform: str = "wptea", priority: int = 2,
                 allow_duplicate: bool = False, skip_filter: bool = False):
        """Add a new task with optional topic filtering.

        Args:
            keyword: Article topic keyword
            category: Category (default: wp-tech)
            platform: Target platform (default: wptea)
            priority: Priority 1-5 (default: 2)
            allow_duplicate: Allow duplicate keywords
            skip_filter: Skip topic filter check

        Returns:
            Task ID or None if rejected
        """
        # Duplicate check FIRST — the topic filter does network searches, so
        # running it before dedup burns time/quota on a topic we will reject.
        if not allow_duplicate:
            dup = self.db.find_duplicate(keyword)
            if dup:
                print(f"[dedup] Rejected: '{keyword}' duplicates #{dup['id']} "
                      f"({dup['status']}) — '{dup['keyword']}'")
                print(f"[dedup] Use --allow-duplicate to add anyway, or "
                      f"`ap status {dup['id']}` to inspect the existing task.")
                return None
            near = self.db.find_duplicate(keyword, include_terminal=True)
            if near:
                print(f"[dedup] Note: same topic was previously "
                      f"{near['status']} as #{near['id']}.")

        # Run topic filter unless explicitly skipped
        if not skip_filter:
            print(f"[filter] Checking topic value: '{keyword}' [{category}]")
            from article_pipeline.topic_filter import filter_topic
            filter_result = filter_topic(keyword, category, mock_search=False)

            recommendation = filter_result.get("recommendation", "low_value")
            reason = filter_result.get("reason", "")
            checks = filter_result.get("checks", {})

            print(f"[filter] Result: {recommendation.upper()}")
            print(f"[filter] Reason: {reason}")
            print(f"[filter] Checks:")
            print(f"  - Homogeneity: score={checks.get('homogeneity', {}).get('score', '?')}, "
                  f"verdict={checks.get('homogeneity', {}).get('verdict', False)}")
            print(f"  - Contrarian: has={checks.get('contrarian', {}).get('has', False)}, "
                  f"verdict={checks.get('contrarian', {}).get('verdict', False)}")
            print(f"  - Counter-intuitive: has={checks.get('counter_intuitive', {}).get('has', False)}, "
                  f"verdict={checks.get('counter_intuitive', {}).get('verdict', False)}")

            # Store filter result in meta for reference
            filter_meta = {
                "filter_result": filter_result,
                "filtered_at": datetime.now(timezone.utc).isoformat(),
            }

            if recommendation == "reject":
                print(f"[filter] Topic rejected. Use --skip-filter to override.")
                return None
            elif recommendation == "low_value":
                print(f"[filter] Topic marked as low_value. Use --skip-filter to add anyway.")
                # Still add to queue but with low priority and filter metadata
                priority = max(priority, 4)  # Bump to low priority
        else:
            filter_meta = {}

        # Add the task
        task_id = self.db.add_task(
            keyword=keyword,
            category=category,
            platform=platform,
            priority=priority,
            allow_duplicate=allow_duplicate
        )

        if task_id:
            # Store filter metadata if any
            if filter_meta:
                import json as _j
                meta = _j.loads(self.db.conn.execute(
                    "SELECT meta_json FROM tasks WHERE id=?", (task_id,)
                ).fetchone()[0] or "{}")
                meta.update(filter_meta)
                self.db.conn.execute(
                    "UPDATE tasks SET meta_json=? WHERE id=?",
                    (_j.dumps(meta, ensure_ascii=False), task_id)
                )
                self.db.conn.commit()

            print(f"[add] Task #{task_id} created: '{keyword}' [{category}] (priority={priority})")
        else:
            print(f"[add] Task not created (duplicate or filtered out)")

        return task_id


def known_categories() -> list[str]:
    """Valid categories = the genre directories that actually ship.

    An unknown category is dangerous rather than merely wrong:
    _map_category_to_genre() silently falls back to "tutorial", so a typo
    produces a tutorial-shaped article under a bogus label. The legacy
    bin/article-pipeline CLI hardcoded this list and drifted; derive it.
    """
    genres_dir = Path(__file__).parent / "genres"
    if not genres_dir.is_dir():
        return ["wp-tech"]
    return sorted(d.name for d in genres_dir.iterdir()
                  if d.is_dir() and not d.name.startswith("_"))


def main():
    """CLI entry point for article-pipeline."""
    import sys
    import argparse

    parser = argparse.ArgumentParser(
        description="Article Pipeline — from keywords to WordPress posts",
        prog="ap"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Add command
    add_parser = subparsers.add_parser("add", help="Add a new article task")
    add_parser.add_argument("keyword", help="Article topic keyword")
    add_parser.add_argument("-c", "--category", default="wp-tech",
                            choices=known_categories(),
                            help="Category (default: wp-tech)")
    add_parser.add_argument("-p", "--platform", default="wptea",
                            help="Target platform (default: wptea)")
    add_parser.add_argument("-P", "--priority", type=int, default=2,
                            help="Priority 1-5 (default: 2)")
    add_parser.add_argument("--allow-duplicate", action="store_true",
                            help="Allow duplicate keywords")
    add_parser.add_argument("--skip-filter", action="store_true",
                            help="Skip topic filter check")

    # Run command
    run_parser = subparsers.add_parser("run", help="Process queued tasks")
    run_parser.add_argument("-l", "--limit", type=int, default=5,
                            help="Max tasks to process (default: 5)")
    run_parser.add_argument("-c", "--category", default=None,
                            help="Only process this category")
    run_parser.add_argument("--max-priority", type=int, default=None,
                            help="Only process tasks with priority <= N")
    run_parser.add_argument("--dry-run", action="store_true",
                            help="Show what would be processed, claim nothing")

    # Resume command ("continue" kept as an alias — README used that name)
    resume_parser = subparsers.add_parser(
        "resume", aliases=["continue"], help="Resume a stuck task")
    resume_parser.add_argument("task_id", type=int, help="Task ID to resume")

    # Status command
    status_parser = subparsers.add_parser(
        "status", help="Show one task in detail (incl. failure history)")
    status_parser.add_argument("task_id", type=int)

    # Recover command
    recover_parser = subparsers.add_parser(
        "recover", help="Requeue tasks stalled mid-cascade")
    recover_parser.add_argument("--max-minutes", type=int, default=30,
                                help="Consider stalled after N minutes (default: 30)")
    recover_parser.add_argument("--dry-run", action="store_true",
                                help="List stalled tasks without touching them")
    recover_parser.add_argument("--include-human-gates", action="store_true",
                                help="Also rewind outline_review/reviewing "
                                     "(destroys work awaiting approval)")

    # Skip command
    skip_parser = subparsers.add_parser("skip", help="Reject/park a task")
    skip_parser.add_argument("task_id", type=int)
    skip_parser.add_argument("--reason", required=True)

    # Schedule check
    sched_parser = subparsers.add_parser(
        "schedule-check", help="Report queue coverage vs publish rhythm")
    sched_parser.add_argument("--notify", action="store_true",
                              help="Send NATS alerts (default: report only)")

    # Doctor
    subparsers.add_parser(
        "doctor", help="Validate config + report queue health")

    # Approve outline command
    approve_parser = subparsers.add_parser("approve-outline", help="Approve outline for TIER_EXTERNAL task")
    approve_parser.add_argument("task_id", type=int, help="Task ID to approve")

    # Publish command
    publish_parser = subparsers.add_parser("publish", help="Publish an approved article")
    publish_parser.add_argument("task_id", type=int, help="Task ID to publish")
    publish_parser.add_argument("--dry-run", action="store_true",
                                help="Convert and show what would be submitted; no network, no post created")
    publish_parser.add_argument("--force", action="store_true",
                                help="Allow republishing a task that already has a published_url (creates a duplicate post)")

    # Review server command (documented in README as :8765 — this is it)
    rs_parser = subparsers.add_parser("review-server",
                                      help="Start the web review UI (default http://127.0.0.1:8765)")
    rs_parser.add_argument("-p", "--port", type=int, default=None,
                           help="Port (default 8765, or $AP_REVIEW_PORT)")
    rs_parser.add_argument("--host", default=None,
                           help="Bind address (default 127.0.0.1, or $AP_REVIEW_HOST)")

    # Review queue command
    subparsers.add_parser("review-queue", help="Show articles awaiting review")

    # Unpublish command
    unpublish_parser = subparsers.add_parser("unpublish", help="Revert a published task to reviewing")
    unpublish_parser.add_argument("task_id", type=int, help="Task ID to unpublish")

    # List command
    list_parser = subparsers.add_parser("list", help="List tasks")
    list_parser.add_argument("-s", "--status", help="Filter by status")
    list_parser.add_argument("-c", "--category", help="Filter by category")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    pipeline = Pipeline()

    if args.command == "add":
        task_id = pipeline.add_task(
            keyword=args.keyword,
            category=args.category,
            platform=args.platform,
            priority=args.priority,
            allow_duplicate=args.allow_duplicate,
            skip_filter=args.skip_filter
        )
        if task_id:
            print(f"Created task #{task_id}")
        else:
            sys.exit(1)

    elif args.command == "run":
        if args.dry_run:
            batch = pipeline.db.peek_next_batch(
                limit=args.limit, category=args.category,
                max_priority=args.max_priority)
            if not batch:
                print("No queued tasks found.")
            else:
                print(f"Would process {len(batch)} task(s) "
                      f"(dry run, nothing claimed):")
                for t in batch:
                    print(f"  #{t['id']} P{t['priority']} "
                          f"[{t['category']}] {t['keyword']}")
        else:
            results = pipeline.run(limit=args.limit, category=args.category,
                                   max_priority=args.max_priority)
            if results:
                print(f"\nCompleted {len(results)} stage transitions")

    elif args.command in ("resume", "continue"):
        pipeline.resume(args.task_id)

    elif args.command == "status":
        task = pipeline.db.get_task(args.task_id)
        if not task:
            print(f"Task #{args.task_id} not found.")
            sys.exit(1)
        import json as _j
        meta = _j.loads(task.get("meta_json") or "{}")
        print(f"#{task['id']}  {task['keyword']}")
        print(f"  status    : {task['status']}")
        print(f"  category  : {task['category']}   platform: {task['platform']}"
              f"   priority: {task['priority']}")
        print(f"  created   : {task['created_at']}")
        print(f"  changed   : {meta.get('status_changed_at', '-')}")
        print(f"  published : {task.get('published_url') or '-'}")
        print(f"  skip      : {task.get('skip_reason') or '-'}")
        stages = [(f, bool(task.get(f))) for f in
                  ("research_note", "synthesis", "framework", "prosody",
                   "compiled_prompt", "outline", "article")]
        print("  outputs   : " + "  ".join(
            f"{'+' if ok else '-'}{name}" for name, ok in stages))
        for k in ("trust_tier", "outline_retries", "writing_retries",
                  "recovery_attempts", "failed_stage"):
            if k in meta:
                print(f"  {k:<10}: {meta[k]}")
        for err in meta.get("error_log", [])[-5:]:
            print(f"  ! {err.get('at', '?')} [{err.get('stage', '?')}] "
                  f"{str(err.get('error', ''))[:120]}")

    elif args.command == "recover":
        if args.dry_run:
            stuck = pipeline.db.get_stuck_tasks(
                max_minutes=args.max_minutes,
                include_human_gates=args.include_human_gates)
            if not stuck:
                print("No stalled tasks.")
            else:
                print(f"{len(stuck)} stalled task(s) (dry run, no changes):")
                for t in stuck:
                    mins = t.get("stuck_minutes")
                    print(f"  #{t['id']:>4} {t['status']:<13} "
                          f"idle={mins if mins is not None else '?'}min  "
                          f"{t['keyword']}")
        else:
            recovered = pipeline.db.recover_stuck(
                max_minutes=args.max_minutes,
                include_human_gates=args.include_human_gates)
            if not recovered:
                print("No stalled tasks to recover.")
            else:
                for r in recovered:
                    print(f"  #{r['id']} {r['was']} -> {r['rolled_back_to']} "
                          f"(attempt {r['attempts']}): {r['keyword']}")

    elif args.command == "skip":
        task = pipeline.db.get_task(args.task_id)
        if not task:
            print(f"Task #{args.task_id} not found.")
            sys.exit(1)
        pipeline.db.update_status(args.task_id, "skipped",
                                 {"skip_reason": args.reason})
        print(f"Task #{args.task_id} skipped: {args.reason}")

    elif args.command == "schedule-check":
        from article_pipeline.scheduler import run_schedule_check
        alerts = run_schedule_check(pipeline.db, auto_notify=args.notify)
        if not alerts:
            print("Queue coverage OK for all configured platforms.")

    elif args.command == "doctor":
        from article_pipeline.config import validate_config
        problems = validate_config()
        print("=== config ===")
        if not problems:
            print("  OK")
        for level, msg in problems:
            print(f"  [{level}] {msg}")
        print("=== queue ===")
        counts = pipeline.db.status_counts()
        if not counts:
            print("  empty")
        for st, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"  {st:<14} {n}")
        stuck = pipeline.db.get_stuck_tasks()
        print(f"=== stalled (>30min in an automated stage): {len(stuck)} ===")
        for t in stuck:
            print(f"  #{t['id']} {t['status']} {t['keyword']}")
        if any(lvl == "error" for lvl, _ in problems):
            sys.exit(1)

    elif args.command == "approve-outline":
        pipeline.approve_outline(args.task_id)

    elif args.command == "publish":
        pipeline.publish(args.task_id, dry_run=args.dry_run, force=args.force)

    elif args.command == "review-server":
        from article_pipeline import review_server
        review_server.run_server(
            port=args.port or review_server.PORT,
            host=args.host or review_server.HOST,
        )

    elif args.command == "review-queue":
        pipeline.show_review_queue()

    elif args.command == "unpublish":
        pipeline.unpublish(args.task_id)

    elif args.command == "list":
        tasks = pipeline.db.list_tasks(status=args.status, category=args.category)
        if not tasks:
            print("No tasks found.")
        else:
            for t in tasks:
                print(f"#{t['id']:3d} | {t['status']:12s} | {t['category']:15s} | {t['keyword']}")
