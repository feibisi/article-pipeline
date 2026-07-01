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
    """Replace ```mermaid blocks with base64-embedded SVG images."""
    import base64
    try:
        meta = json.loads(meta_json or "{}")
        diagrams = meta.get("diagrams", {})
    except (json.JSONDecodeError, TypeError):
        return md_text

    if not diagrams:
        return md_text

    for idx_str, svg_path in diagrams.items():
        svg_file = Path(svg_path)
        if not svg_file.exists():
            continue
        svg_content = svg_file.read_text()
        b64 = base64.b64encode(svg_content.encode()).decode()
        data_uri = f'data:image/svg+xml;base64,{b64}'

        # Find the corresponding ```mermaid block and replace
        mermaid_blocks = list(re.finditer(
            r'```mermaid\s*\n.*?```', md_text, re.DOTALL))
        idx = int(idx_str)
        if idx < len(mermaid_blocks):
            m = mermaid_blocks[idx]
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
    """Extract first paragraph text as excerpt from Gutenberg HTML."""
    m = re.search(r'<!-- wp:paragraph -->\s*<p>(.+?)</p>', gutenberg_html)
    if m:
        # Strip HTML tags
        return re.sub(r'<[^>]+>', '', m.group(1))[:200]
    return ""


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

        if result.returncode == 0 or url_match:
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
                "message": output[-500:] if output else "Unknown error",
            }

    except subprocess.CalledProcessError as e:
        return {"error": "ssh_failed", "message": str(e)}
    finally:
        os.unlink(tmp_path)


def _translate_categories() -> dict:
    return {
        "新闻资讯": 1, "专题报道": 78, "产品发布": 104,
        "基础设施": 79, "平台优化": 81, "开发路线": 83,
        "推送热点": 113, "生态系统": 9, "电子商务": 85, "茶话会": 5,
    }


def publish_to_wp(task_id: int, title: str, article: str,
                  meta_description: str = "",
                  platform: str = "wptea",
                  category: str = "生态系统") -> dict:
    """Publish to WordPress with Gutenberg blocks. Falls back to translate bridge."""
    config = load_config()
    wp_config = config.get("wordpress", {})
    wp_url = wp_config.get(f"{platform}_url")

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
                    return {
                        "published": True,
                        "url": data.get("link", ""),
                        "post_id": data.get("id"),
                        "platform": platform,
                        "via": "rest_api",
                    }
            except (requests.ConnectionError, requests.HTTPError):
                pass
            except requests.RequestException:
                pass

    # Fallback: translate SSH bridge
    if platform == "wptea":
        return _publish_via_translate(title, article, category)

    return {"error": "no_publishing_path",
            "message": f"No working publishing path for {platform}"}
