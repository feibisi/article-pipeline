"""Mermaid diagram rendering — extract from articles and render to SVG via beautiful-mermaid CLI."""
import subprocess
import re
import tempfile
from pathlib import Path

MERMAID_CLI = Path.home() / "Projects" / "beautiful-mermaid" / "cli.mjs"
MERMAID_THEME = "tokyo-night-storm"


def extract_mermaid_blocks(article: str) -> list[dict]:
    """Extract all ```mermaid code blocks from an article. Returns list of {index, code}."""
    blocks = []
    for i, m in enumerate(re.finditer(r'```mermaid\s*\n(.*?)```', article, re.DOTALL)):
        blocks.append({"index": i, "code": m.group(1).strip()})
    return blocks


def render_to_svg(mermaid_code: str, theme: str = MERMAID_THEME) -> str | None:
    """Render Mermaid code to SVG string via beautiful-mermaid CLI."""
    if not MERMAID_CLI.exists():
        return None
    try:
        result = subprocess.run(
            ["node", str(MERMAID_CLI), "--theme", theme],
            input=mermaid_code,
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def render_article_diagrams(article: str, output_dir: Path, task_id: int) -> dict:
    """Extract and render all Mermaid diagrams in an article. Returns mapping of block index→svg path."""
    blocks = extract_mermaid_blocks(article)
    if not blocks:
        return {}

    output_dir.mkdir(parents=True, exist_ok=True)
    rendered = {}

    for block in blocks:
        svg = render_to_svg(block["code"])
        if svg:
            fname = f"task{task_id}_diagram{block['index']}.svg"
            fpath = output_dir / fname
            fpath.write_text(svg)
            rendered[block["index"]] = str(fpath)

    return rendered


def replace_mermaid_with_img(article: str, rendered: dict[int, str]) -> str:
    """Replace ```mermaid blocks with <img> tags pointing to rendered SVGs."""
    blocks = list(re.finditer(r'```mermaid\s*\n.*?```', article, re.DOTALL))
    result = article
    # Replace from last to first to preserve positions
    for i, block in reversed(list(enumerate(blocks))):
        if i in rendered:
            svg_path = rendered[i]
            img_tag = f'\n\n<img src="{svg_path}" alt="Mermaid diagram" loading="lazy">\n\n'
            result = result[:block.start()] + img_tag + result[block.end():]
    return result
