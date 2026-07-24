"""WordPress publishing — REST API with translate SSH bridge fallback.

Uses translate's converter.py for Gutenberg block format.
"""
from article_pipeline.config import load_config
import os
import json
import tempfile
import subprocess
import requests
import yaml
import re
from pathlib import Path
from base64 import b64encode



def _wp_auth_header():
    username = os.environ.get("AP_WP_USERNAME", "")
    app_password = os.environ.get("AP_WP_APP_PASSWORD", "")
    if not username or not app_password:
        return {}
    credentials = b64encode(f"{username}:{app_password}".encode()).decode()
    return {"Authorization": f"Basic {credentials}"}


def _embed_mermaid_svgs(md_text: str, meta_json: str) -> str:
    """Replace ```mermaid blocks with base64-embedded SVG images.

    Note: the SVG is inlined as a data: URI. WordPress strips data: URIs from
    post content for any user without the `unfiltered_html` capability, so a
    non-admin application password will publish diagram-less articles. Uploading
    the SVG to the media library is the durable fix (see audit notes).
    """
    import base64
    try:
        meta = json.loads(meta_json or "{}")
        diagrams = meta.get("diagrams", {})
    except (json.JSONDecodeError, TypeError):
        return md_text

    if not diagrams:
        return md_text

    # Scan the fences ONCE and substitute from last to first. The previous
    # version re-scanned inside the loop, so after replacing diagram 0 the
    # remaining fences shifted down by one: diagram 1's SVG was pasted where
    # diagram 2 belonged, diagram 2 was dropped entirely, and diagram 1's raw
    # ```mermaid source leaked into the published article.
    mermaid_blocks = list(re.finditer(
        r'```mermaid\s*\n.*?```', md_text, re.DOTALL))

    for idx, m in reversed(list(enumerate(mermaid_blocks))):
        svg_path = diagrams.get(str(idx)) or diagrams.get(idx)
        if not svg_path:
            continue
        svg_file = Path(svg_path)
        if not svg_file.exists():
            continue
        b64 = base64.b64encode(svg_file.read_text().encode()).decode()
        data_uri = f'data:image/svg+xml;base64,{b64}'
        img_tag = f'<img src="{data_uri}" alt="Mermaid diagram {idx}" />'
        md_text = md_text[:m.start()] + img_tag + md_text[m.end():]

    return md_text


def _markdown_to_gutenberg(md_text: str, article_type: str = "",
                           meta_json: str = "") -> str:
    """Convert Markdown to Gutenberg block format."""
    from article_pipeline.converter import md_to_gutenberg, detect_article_type
    if not article_type:
        article_type = detect_article_type(md_text)
    # Embed Mermaid SVGs before markdown conversion
    md_text = _embed_mermaid_svgs(md_text, meta_json)
    # Strip leading markdown code fence wrapper (LLM output format)
    md_text = re.sub(r'^```(?:markdown|md)?\s*\n', '', md_text)
    md_text = re.sub(r'\n```\s*$', '', md_text)
    return md_to_gutenberg(md_text, skip_first_h1=True, article_type=article_type)


def _extract_excerpt(gutenberg_html: str) -> str:
    """Extract the first *body* paragraph as excerpt from Gutenberg HTML.

    Paragraphs nested inside a wp:group (the type notice boxes) are skipped:
    otherwise every "security" article got the excerpt
    "安全通告 — 请相关站长及时检查并更新受影响的插件或组件。", which is what
    shows up in archive listings, search results and social previews.
    """
    # Drop wp:group ... /wp:group regions first.
    body = re.sub(r'<!-- wp:group.*?<!-- /wp:group -->', '', gutenberg_html,
                  flags=re.DOTALL)
    m = re.search(r'<!-- wp:paragraph -->\s*<p>(.+?)</p>', body, re.DOTALL)
    if m:
        # Strip HTML tags
        return re.sub(r'<[^>]+>', '', m.group(1)).strip()[:200]
    return ""


def _count_blocks(gutenberg_html: str) -> dict:
    """Count Gutenberg blocks by type — used by dry-run to show what will ship."""
    counts: dict[str, int] = {}
    for name in re.findall(r'<!-- wp:([a-z0-9-]+)', gutenberg_html):
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def _publish_via_translate(title: str, article: str, category: str = "生态系统") -> dict:
    """Publish via translate VM's WordPressClient (bypasses REST API)."""
    category_name = category if category in _translate_categories() else "生态系统"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False,
                                      encoding="utf-8", prefix="ap_") as f:
        f.write(f"# {title}\n\n{article}")
        tmp_path = f.name

    try:
        remote_path = f"/tmp/ap_article_{os.getpid()}.md"
        subprocess.run(["scp", tmp_path, f"translate:{remote_path}"],
                       capture_output=True, check=True, timeout=15)

        result = subprocess.run(
            ["ssh", "translate",
             f"cd ~/Projects/wptea-tools && python3 cli.py publish {remote_path}"
             f" --site wptea --category '{category_name}' --publish"],
            capture_output=True, text=True, timeout=60
        )

        subprocess.run(["ssh", "translate", f"rm -f {remote_path}"],
                       capture_output=True, timeout=5)

        output = result.stdout + result.stderr
        url_match = re.search(r'(https?://wptea\.com/\S+)', output)
        post_id_match = re.search(r'ID=(\d+)', output)

        # A publish only counts as successful if it produced a real post URL or
        # post ID. Previously `returncode == 0` alone was treated as success, so
        # a command that exited cleanly without actually creating a post
        # returned published=True with an empty url — which is exactly how the
        # DB ended up with "done" tasks whose published_url was blank and whose
        # supposed URLs 404 on the live site.
        if url_match or post_id_match:
            return {
                "published": True,
                "url": url_match.group(1) if url_match else "",
                "post_id": int(post_id_match.group(1)) if post_id_match else None,
                "platform": "wptea",
                "via": "translate",
            }
        else:
            return {
                "error": "translate_publish_failed",
                "message": (
                    "命令退出码为 0 但未返回文章 URL/ID，无法确认发布成功；"
                    f"输出: {output[-500:]}" if result.returncode == 0
                    else (output[-500:] if output else "Unknown error")
                ),
            }

    except subprocess.CalledProcessError as e:
        return {"error": "ssh_failed", "message": str(e)}
    except subprocess.TimeoutExpired as e:
        # Previously uncaught: a hung scp/ssh raised out of publish_to_wp instead
        # of returning an error dict, so callers (CLI publish, review server
        # batch approve) crashed mid-batch rather than recording a failure.
        return {"error": "ssh_timeout",
                "message": f"scp/ssh 超时（{e.timeout}s），发布状态未知，请人工核对站点"}
    finally:
        os.unlink(tmp_path)


def _translate_categories() -> dict:
    return {
        "新闻资讯": 1, "专题报道": 78, "产品发布": 104,
        "基础设施": 79, "平台优化": 81, "开发路线": 83,
        "推送热点": 113, "生态系统": 9, "电子商务": 85, "茶话会": 5,
    }


def _already_published(task_id: int) -> dict | None:
    """Return the recorded publication if this task already has one."""
    try:
        from article_pipeline.db import TaskDB
        t = TaskDB().get_task(task_id)
    except Exception:
        return None
    if not t:
        return None
    url = (t.get("published_url") or "").strip()
    if not url:
        try:
            meta = json.loads(t.get("meta_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            meta = {}
        url = (meta.get("published_url") or "").strip()
    if url:
        return {"url": url, "status": t.get("status", "")}
    return None


def publish_to_wp(task_id: int, title: str, article: str,
                  meta_description: str = "",
                  platform: str = "wptea",
                  category: str = "生态系统",
                  dry_run: bool = False,
                  force: bool = False) -> dict:
    """Publish to WordPress with Gutenberg blocks. Falls back to translate bridge.

    Args:
        dry_run: 不联网、不 ssh，只做转换并返回将要提交的内容摘要。
        force: 允许对已经有 published_url 的任务重复发布（会在站点上产生第二篇）。
    """
    config = load_config()
    wp_config = config.get("wordpress", {})
    wp_url = wp_config.get(f"{platform}_url")

    # --- Idempotency guard ---
    # WordPress 的 REST /posts 和 translate 桥都是"每次调用创建一篇新文章"，
    # 没有任何去重键。unpublish 只把状态改回 reviewing、并不删除线上文章
    # （pipeline.py:698 自己也承认），所以 unpublish → publish 会在站点上留下
    # 两篇内容相同的文章。这里挡住重复发布，除非调用方显式 force。
    existing = _already_published(task_id)
    if existing and not force and not dry_run:
        return {"error": "already_published",
                "message": f"任务 #{task_id} 已记录发布地址 {existing['url']}；"
                           f"重复发布会在站点上产生第二篇。确认要再发一遍请用 force=True。",
                "url": existing["url"]}

    # Convert to Gutenberg block format
    # Look up meta_json for embedded Mermaid SVGs
    meta_json = ""
    try:
        from article_pipeline.db import TaskDB
        db = TaskDB()
        t = db.get_task(task_id)
        if t:
            meta_json = t.get("meta_json", "{}") or "{}"
    except Exception:
        pass
    gutenberg_content = _markdown_to_gutenberg(article, meta_json=meta_json)
    excerpt = _extract_excerpt(gutenberg_content) or meta_description

    if dry_run:
        headers = _wp_auth_header()
        category_name = (category if category in _translate_categories()
                         else "生态系统")
        return {
            "published": False,
            "dry_run": True,
            "task_id": task_id,
            "title": title,
            "platform": platform,
            "category": category_name,
            "category_adjusted": category_name != category,
            "excerpt": excerpt,
            "content_chars": len(gutenberg_content),
            "block_counts": _count_blocks(gutenberg_content),
            "gutenberg": gutenberg_content,
            # 只报告凭据"在不在"，绝不回传凭据内容
            "planned_route": ("rest_api" if (wp_url and headers)
                              else ("translate" if platform == "wptea"
                                    else "none")),
            "rest_credentials_present": bool(headers),
            "rest_endpoint_configured": bool(wp_url),
            "already_published": existing["url"] if existing else None,
        }

    # Try REST API first
    if wp_url:
        headers = _wp_auth_header()
        if headers:
            headers["Content-Type"] = "application/json"

            payload = {
                "title": title, "content": gutenberg_content,
                "excerpt": excerpt, "status": "publish", "format": "standard",
            }
            if meta_description:
                payload["meta"] = {"_yoast_wpseo_metadesc": meta_description}

            try:
                resp = requests.post(f"{wp_url}/posts", headers=headers,
                                     json=payload, timeout=30)
                if resp.status_code < 500:
                    resp.raise_for_status()
                    data = resp.json()
                    post_id = data.get("id")
                    link = data.get("link", "")
                    # Same honesty rule as the translate bridge: a 2xx alone is
                    # not proof a post exists. Without an id/link we must not
                    # report published=True — that is how the DB collected
                    # "done" rows whose URLs 404.
                    if post_id or link:
                        return {
                            "published": True,
                            "url": link,
                            "post_id": post_id,
                            "status": data.get("status", ""),
                            "platform": platform,
                            "via": "rest_api",
                        }
                    return {
                        "error": "rest_publish_unverified",
                        "message": (f"REST 返回 {resp.status_code} 但响应里没有 "
                                    f"id/link，无法确认文章已创建；"
                                    f"响应片段: {resp.text[:300]}"),
                    }
            except (requests.ConnectionError, requests.HTTPError):
                pass
            except requests.RequestException:
                pass
            except ValueError:
                # resp.json() on a non-JSON body (HTML error page / WAF block)
                pass

    # Fallback: translate SSH bridge.
    # NOTE: this path ships *Markdown* and lets translate's own converter build
    # the blocks, so none of the Gutenberg work above (tables, separators,
    # list-item blocks) applies here — the two routes produce visibly different
    # articles. We at least fold in the rendered Mermaid diagrams, otherwise
    # every diagram is lost on the only route that has ever actually run.
    if platform == "wptea":
        return _publish_via_translate(
            title, _embed_mermaid_svgs(article, meta_json), category)

    return {"error": "no_publishing_path",
            "message": f"No working publishing path for {platform}"}
