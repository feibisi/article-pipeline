#!/usr/bin/env python3
"""Article review web server — Jinja2 templates + Pico CSS + structured approval."""
import json
import os
import re
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from pathlib import Path


import jinja2

# Add parent dir to path for article_pipeline imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from article_pipeline.db import TaskDB
from article_pipeline.text_utils import fix_em_dashes

PORT = 8765
AUTH_TOKEN = os.environ.get("AP_REVIEW_TOKEN", "")  # Set this env var to enable POST auth
BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

db = TaskDB()

# Jinja2 environment
jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=jinja2.select_autoescape(["html"]),
    undefined=jinja2.Undefined,
)

# Tag sets imported from review module (for template rendering)
HEAVY_TAGS = set()
FILLER_TAGS = set()


def _load_tag_sets():
    """Load tag classification from review module."""
    try:
        from article_pipeline.review import HEAVY_TAGS as ht, FILLER_TAGS as ft
        global HEAVY_TAGS, FILLER_TAGS
        HEAVY_TAGS = ht
        FILLER_TAGS = ft
    except ImportError:
        pass


_load_tag_sets()


def _render(template_name: str, **kwargs) -> str:
    """Render a Jinja2 template with common context."""
    tmpl = jinja_env.get_template(template_name)
    ctx = {"heavy_tags": HEAVY_TAGS, "filler_tags": FILLER_TAGS}
    ctx.update(kwargs)
    return tmpl.render(**ctx)


def md_to_html(text: str) -> str:
    """Convert Markdown to HTML, sanitizing output for safe rendering."""
    if not text:
        return ""
    import markdown as md_lib
    import nh3
    # Strip leading markdown code fence wrapper (LLM output format)
    text = re.sub(r'^```(?:markdown|md)?\s*\n', '', text)
    text = re.sub(r'\n```\s*$', '', text)
    raw_html = md_lib.markdown(text, extensions=[
        'tables', 'fenced_code', 'codehilite',
        'toc', 'sane_lists',
    ], output_format='html5')
    # Sanitize: strip scripts, event handlers, and other XSS vectors
    # from web-fetched content that may pass through research notes
    return nh3.clean(raw_html, tags=nh3.ALLOWED_TAGS | {
        'img', 'span', 'div', 'pre', 'code', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'table', 'thead', 'tbody', 'tr', 'th', 'td', 'blockquote', 'hr', 'br',
        'a', 'p', 'ul', 'ol', 'li', 'em', 'strong', 'del', 'sub', 'sup',
        'details', 'summary',
    }, attributes={
        'a': {'href', 'title', 'target', 'rel'},
        'img': {'src', 'alt', 'title', 'width', 'height'},
        'td': {'align', 'valign', 'colspan', 'rowspan'},
        'th': {'align', 'valign', 'colspan', 'rowspan'},
        'code': {'class'},
        'pre': {'class'},
        'span': {'class'},
        'div': {'class'},
        '*': {'id'},
    }, link_rel=None)


def _get_review(task_id: int) -> dict:
    """Get latest review results for a task, with defaults for missing fields."""
    c = db.conn.cursor()
    c.execute("SELECT * FROM review_log WHERE task_id=? ORDER BY id DESC LIMIT 1", (task_id,))
    row = c.fetchone()
    if not row:
        return None
    data = json.loads(row['check_results'])

    # Helper to fill defaults into a (possibly empty) sub-dict
    def _fill(d, defaults):
        if not isinstance(d, dict):
            d = {}
        for k, v in defaults.items():
            d.setdefault(k, v)
        return d

    data["humanizer"] = _fill(data.get("humanizer"), {"total": 0, "grade": "?", "pass": False, "dimensions": {}})
    data["ai_check"] = _fill(data.get("ai_check"), {"score": 0, "flags": [], "pass": False})
    data["fabrication"] = _fill(data.get("fabrication"), {"score": 0, "fabrication_flags": 0, "details": [], "pass": True})
    data["semantic_facts"] = _fill(data.get("semantic_facts"), {"verified": 0, "unverified": 0, "details": [],
                                                                  "verified_details": [], "pass": True, "total_claims": 0})
    data["format"] = _fill(data.get("format"), {"has_h2": False, "has_intro": False, "para_count": 0, "pass": False})
    data["word_count"] = _fill(data.get("word_count"), {"chars": 0, "pass": False})
    data.setdefault("suggestions", [])
    data.setdefault("geo", {"score": 0, "total": 0, "pass": False, "dimensions": {}, "suggestions": []})
    data.setdefault("overall_score", 0)
    data.setdefault("overall_pass", False)
    return data


def _build_list_item(task: dict) -> dict:
    """Build display data for a list item."""
    review = _get_review(task['id'])
    feedback_history = db.get_feedback_history(task['id'])
    revision_count = len([f for f in feedback_history if f.get('verdict') == 'revision'])

    item = {
        "id": task['id'],
        "keyword": task.get('keyword', '') or task.get('title', ''),
        "category": task.get('category', ''),
        "status": task.get('status', ''),
        "overall": 0, "ai": 0, "ai_flags": 0, "fab": 0,
        "sem_verified": 0, "sem_total": 0,
        "hz": 0, "hz_grade": "",
        "chars": len(task.get('article', '') or ''),
        "geo": 0,
        "version": task.get('version', 1),
        "pass": False, "revision_count": revision_count,
    }

    # Add trust tier from task metadata
    import json as _json
    meta = _json.loads(task.get('meta_json', '{}') or '{}')
    item["trust_tier"] = meta.get("trust_tier", "TIER_INTERNAL")

    if review:
        ai = review.get('ai_check', {})
        fab = review.get('fabrication', {})
        sem = review.get('semantic_facts', {})
        hz = review.get('humanizer', {})
        wc = review.get('word_count', {})
        item["overall"] = review.get('overall_score', 0)
        item["ai"] = ai.get('score', 0)
        item["ai_flags"] = len(ai.get('flags', []))
        item["fab"] = fab.get('score', 0)
        item["sem_verified"] = sem.get('verified', 0)
        item["sem_total"] = sem.get('total_claims', 0)
        item["hz"] = hz.get('total', 0)
        item["hz_grade"] = hz.get('grade', '')
        item["chars"] = wc.get('chars', item['chars'])
        item["geo"] = review.get('geo', {}).get('total', 0)
        item["pass"] = review.get('overall_pass', False)

    return item


class ReviewHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_html(self, content: str, status: int = 200):
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(content.encode())

    def _send_static(self, filepath: Path):
        if not filepath.exists():
            self.send_response(404)
            self.end_headers()
            return
        ext = filepath.suffix
        mime = {'.css': 'text/css', '.js': 'application/javascript', '.png': 'image/png'}.get(ext, 'text/plain')
        self.send_response(200)
        self.send_header('Content-Type', f'{mime}; charset=utf-8')
        self.send_header('Cache-Control', 'public, max-age=3600')
        self.end_headers()
        self.wfile.write(filepath.read_bytes())

    def _redirect(self, path: str):
        self.send_response(302)
        self.send_header('Location', path)
        self.end_headers()

    def _read_post_body(self) -> dict:
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8') if length else ''
        return parse_qs(body)

    # ── GET routes ──

    def do_GET(self):
        path = urlparse(self.path).path
        params = parse_qs(urlparse(self.path).query)

        if path == '/':
            self._list()
        elif path == '/view':
            self._view(int(params.get('id', [0])[0]))
        elif path == '/revision':
            self._show_revision_form(int(params.get('id', [0])[0]))
        elif path.startswith('/static/'):
            fname = path[len('/static/'):]
            self._send_static(STATIC_DIR / fname)
        else:
            self._send_html(_render("result.html", title="Not Found", message="Page not found."), 404)


    # ── HEAD routes (same as GET, body discarded) ──

    def do_HEAD(self):
        self.do_GET()

    # ── POST routes ──

    def _check_auth(self) -> bool:
        """Check Bearer token for POST requests. Returns True if authorized."""
        if not AUTH_TOKEN:
            return True
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {AUTH_TOKEN}":
            return True
        self.send_response(401)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Unauthorized")
        return False

    def do_POST(self):
        if not self._check_auth():
            return
        path = urlparse(self.path).path
        params = parse_qs(urlparse(self.path).query)

        if path == '/approve':
            self._approve(int(params.get('id', [0])[0]))
        elif path == '/reject':
            self._reject(int(params.get('id', [0])[0]))
        elif path == '/submit-revision':
            self._submit_revision(int(params.get('id', [0])[0]))
        elif path == '/auto-revise':
            self._auto_revise(int(params.get('id', [0])[0]))
        elif path == '/batch-approve':
            self._batch_approve()
        else:
            self.send_response(404)
            self.end_headers()

    # ── List page ──

    def _list(self):
        tasks = db.list_tasks(status="reviewing")
        items = [_build_list_item(t) for t in tasks]
        pass_count = sum(1 for i in items if i['pass'])
        fail_count = len(items) - pass_count
        avg_score = sum(i['overall'] for i in items) / len(items) if items else 0

        page = _render("list.html",
                        tasks=tasks, items=items,
                        pass_count=pass_count, fail_count=fail_count,
                        avg_score=avg_score)
        self._send_html(page)

    # ── Detail page ──

    def _view(self, task_id: int):
        task = db.get_task(task_id)
        if not task:
            self._send_html(_render("result.html", title="Not Found", message="Article not found."), 404)
            return

        review = _get_review(task_id)
        feedback_history = db.get_feedback_history(task_id)
        review_history = db.get_review_history(task_id)
        revision_count = len([f for f in feedback_history if f.get('verdict') == 'revision'])
        version = task.get('version', 1)
        prev_article = task.get('article_text_prev', '')

        # Parse outline JSON
        outline_parsed = None
        outline_raw = task.get('outline', '')
        if outline_raw:
            try:
                outline_parsed = json.loads(outline_raw)
            except (json.JSONDecodeError, TypeError):
                outline_parsed = None

        # Pre-process: strip ```mermaid blocks before markdown conversion
        # (codehilite doesn't know mermaid — it tries to highlight it as code)
        raw_article = task.get('article', '')
        meta = json.loads(task.get('meta_json', '{}') or '{}')
        diagrams = meta.get('diagrams', {})
        mermaid_placeholders = {}  # placeholder_key → svg_content
        if diagrams:
            import re as _re
            article_for_md = raw_article
            mermaid_blocks = list(_re.finditer(
                r'```mermaid\s*\n(.*?)```', article_for_md, _re.DOTALL))
            # Replace from last to first to preserve positions
            for i, m in reversed(list(enumerate(mermaid_blocks))):
                idx_str = str(i)
                if idx_str in diagrams:
                    svg_file = Path(diagrams[idx_str])
                    if svg_file.exists():
                        ph = f'<!--MERMAID_PLACEHOLDER_{i}-->'
                        article_for_md = (article_for_md[:m.start()] + ph +
                                          article_for_md[m.end():])
                        mermaid_placeholders[ph] = svg_file.read_text()

            article_html = md_to_html(article_for_md)

            # Inject SVGs into placeholders
            for ph, svg_content in mermaid_placeholders.items():
                fig = f'<figure class="mermaid-diagram">{svg_content}<figcaption>图 {ph.split("_")[-1]}</figcaption></figure>'
                article_html = article_html.replace(ph, fig)
        else:
            article_html = md_to_html(raw_article)

        research_note_html = md_to_html(task.get('research_note', ''))

        # Build version history with score deltas
        version_scores = []
        for i, rh in enumerate(review_history):
            results = rh.get("check_results", {})
            version_scores.append({
                "version": rh.get("version", i + 1),
                "score": results.get("overall_score", 0),
                "passed": rh.get("passed", False),
                "ai_score": results.get("ai_check", {}).get("score", 0),
                "fab_score": results.get("fabrication", {}).get("score", 0),
                "chars": results.get("word_count", {}).get("chars", 0),
                "created_at": rh.get("created_at", "")[:16],
            })

        trust_tier = meta.get("trust_tier", "TIER_INTERNAL")
        page = _render("detail.html",
                        task={**task, 'outline_parsed': outline_parsed,
                              'research_note_html': research_note_html,
                              'trust_tier': trust_tier},
                        review=review,
                        feedback_history=feedback_history,
                        version_scores=version_scores,
                        revision_count=revision_count,
                        article_html=article_html,
                        prev_article=prev_article)
        self._send_html(page)

    # ── Revision form ──

    def _show_revision_form(self, task_id: int):
        task = db.get_task(task_id)
        if not task:
            self._send_html(_render("result.html", title="Not Found", message="Article not found."), 404)
            return

        review = _get_review(task_id)
        suggestions = review.get('suggestions', []) if review else []
        has_ai_suggestion = any(s.get('category') == 'ai_tone' for s in suggestions)
        has_fact_suggestion = any(s.get('category') in ('fact_verification', 'fabrication') for s in suggestions)

        page = _render("revision.html",
                        task=task,
                        suggestions=suggestions,
                        has_ai_suggestion=has_ai_suggestion,
                        has_fact_suggestion=has_fact_suggestion)
        self._send_html(page)

    # ── POST: Approve ──

    def _approve(self, task_id: int):
        task = db.get_task(task_id)
        if not task or task['status'] != 'reviewing':
            self._redirect('/')
            return

        review = _get_review(task_id)
        score = review.get('overall_score', 0) if review else 0
        db.add_feedback(task_id, "human", "approve", score,
                         {"notes": "Approved via review server"})

        title = task.get('title') or task['keyword']
        article = task.get('article', '')
        meta_desc = task.get('meta_description', '')

        from article_pipeline.publish import publish_to_wp
        category = self._guess_category(task.get('keyword', ''))
        result = publish_to_wp(task_id, title, article, meta_desc,
                               task.get('platform', 'wptea'), category)

        if 'error' in result:
            self._send_html(_render("result.html",
                                     title="Publish Failed",
                                     message=f"{result.get('error')}: {result.get('message', '')}",
                                     back_url=f"/view?id={task_id}"))
        else:
            db.update_status(task_id, "done", {"published_url": result.get("url", "")})
            self._redirect('/')

    # ── POST: Reject ──

    def _reject(self, task_id: int):
        task = db.get_task(task_id)
        if not task:
            self._redirect('/')
            return
        db.update_status(task_id, "rejected", {"skip_reason": "quality"})
        db.add_feedback(task_id, "human", "reject", 0,
                         {"notes": "Rejected via review server"})
        self._redirect('/')

    # ── POST: Submit revision (human feedback → AI revise → new version) ──

    def _submit_revision(self, task_id: int):
        task = db.get_task(task_id)
        if not task:
            self._redirect('/')
            return

        params = self._read_post_body()
        issues = params.get('issue', [])
        notes = params.get('notes', [''])[0].strip()

        # Build feedback text from checkboxes + free text
        feedback_parts = []
        if issues:
            feedback_parts.append("问题: " + ", ".join(issues))
        if notes:
            feedback_parts.append(notes)

        if not feedback_parts:
            self._redirect(f'/view?id={task_id}')
            return

        feedback_text = "\n".join(feedback_parts)

        if "conclusion" in feedback_text.lower() or "结论" in feedback_text:
            feedback_text += "\n确保结论有明确立场，不要绕弯。用具体比喻或对比让人记住。"

        from article_pipeline.writer import revise_with_human_feedback
        from article_pipeline.review import run_self_review

        result = revise_with_human_feedback(
            task['keyword'], task.get('article', ''),
            feedback_text, task.get('research_note', '')
        )

        if 'error' in result:
            self._send_html(_render("result.html",
                                     title="Revision Failed",
                                     message=f"Revision error: {result['error']}",
                                     back_url=f"/view?id={task_id}"))
            return

        # Save as new version
        revised = fix_em_dashes(result['article'])
        old_ver = task.get('version', 1)
        new_ver = db.new_version(task_id, revised)

        # Re-run review
        review = run_self_review(revised, "A", task.get('research_note', ''),
                                      category=task.get("category", ""))
        db.add_review_entry(task_id, review, passed=review.get('overall_pass', False))
        db.add_feedback(task_id, "human", "revision",
                         review.get('overall_score', 0),
                         {"issues": issues, "notes": notes})

        self._redirect(f'/view?id={task_id}')

    # ── POST: Auto-revise ──

    def _auto_revise(self, task_id: int):
        task = db.get_task(task_id)
        if not task:
            self._redirect('/')
            return

        review = _get_review(task_id)
        suggestions = review.get('suggestions', []) if review else []
        if not suggestions:
            self._send_html(_render("result.html",
                                     title="Error",
                                     message="No suggestions to auto-revise.",
                                     back_url="/"))
            return

        from article_pipeline.writer import write_article_with_feedback
        from article_pipeline.review import run_self_review
        outline = json.loads(task.get('outline', '{}') or '{}')
        result = write_article_with_feedback(
            task['keyword'], task['category'], outline,
            task.get('research_note', ''), task.get('article', ''),
            suggestions
        )

        if 'error' in result:
            self._send_html(_render("result.html",
                                     title="Auto-Revise Failed",
                                     message=result.get('error', 'Unknown error'),
                                     back_url=f"/view?id={task_id}"))
            return

        # Save as new version
        revised = fix_em_dashes(result['article'])
        db.new_version(task_id, revised)
        db.add_feedback(task_id, 'auto', 'revision', 0,
                        {'notes': f'Auto-revised with {len(suggestions)} suggestions'})

        new_review = run_self_review(revised, 'A',
                                      task.get('research_note', ''),
                                      category=task.get("category", ""))
        db.add_review_entry(task_id, new_review, passed=new_review.get('overall_pass', False))
        self._redirect(f'/view?id={task_id}')

    # ── POST: Batch approve ──

    def _batch_approve(self):
        params = self._read_post_body()
        ids = params.get('ids', [])
        if not ids:
            self._redirect('/')
            return

        published, failed = [], []
        for tid_str in ids:
            tid = int(tid_str)
            task = db.get_task(tid)
            if not task or task['status'] != 'reviewing':
                continue
            from article_pipeline.publish import publish_to_wp
            category = self._guess_category(task.get('keyword', ''))
            result = publish_to_wp(tid, task.get('title') or task['keyword'],
                                   task.get('article', ''),
                                   task.get('meta_description', ''),
                                   task.get('platform', 'wptea'), category)
            if 'error' in result:
                failed.append((tid, result.get('error', 'unknown')))
            else:
                db.update_status(tid, 'done', {'published_url': result.get('url', '')})
                db.add_feedback(tid, 'human', 'approve', 0,
                                {'notes': f'Batch approved. URL: {result.get("url", "")}'})
                published.append(tid)

        msg = f'Published {len(published)} articles.'
        if failed:
            msg += f' Failed: {len(failed)}'
        self._send_html(_render("result.html", title="Batch Result",
                                 message=msg, detail=str(failed[:5]) if failed else ""))

    # ── Helpers ──

    @staticmethod
    def _guess_category(keyword):
        kw = (keyword or '').lower()
        if any(w in kw for w in ['安全', '漏洞', '审计', '防护']):
            return '基础设施'
        if any(w in kw for w in ['性能', '优化', '缓存', '加速']):
            return '平台优化'
        if any(w in kw for w in ['开发', 'api', '部署', 'ci', 'github', '自动化']):
            return '开发路线'
        if any(w in kw for w in ['版本', '新特性', '发布', '更新']):
            return '新闻资讯'
        if any(w in kw for w in ['电商', 'woocommerce', '支付']):
            return '电子商务'
        return '生态系统'


if __name__ == '__main__':
    print(f'Review server: http://localhost:{PORT}')
    server = HTTPServer(('0.0.0.0', PORT), ReviewHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
