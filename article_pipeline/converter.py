"""Markdown → Gutenberg 块格式转换器（v4：清洁排版 + 分隔线 + 无 emoji）。"""


import json
import re
import markdown
from bs4 import BeautifulSoup, NavigableString, Tag

# 启用的 markdown 扩展
MD_EXTENSIONS = [
    "tables",
    "fenced_code",
    "nl2br",       # 单换行 → <br>，避免段落内换行丢失
    "sane_lists",  # 更严格的列表解析
]

# 文章类型到分类的映射（用于自动检测）
ARTICLE_TYPE_KEYWORDS = {
    "security": ["漏洞", "CVE-", "后门", "恶意", "攻击", "安全", "Wordfence", "Patchstack", "供应链"],
    "release": ["发布", "版本", "更新", "beta", "RC", "release", "changelog", "新增功能"],
    "weekly": ["周报", "weekly", "本周", "上周", "社区周报"],
    "plugin": ["插件", "plugin", "WordPress 插件", "WooCommerce"],
    "service": ["服务", "托管", "hosting", "SaaS", "平台", "在线"],
}

# emoji 正则：匹配常见 emoji 字符
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"  # 杂项符号和象形文字
    "\U00002702-\U000027B0"  # 装饰符号
    "\U0000FE00-\U0000FE0F"  # 变体选择符
    "\U0000200D"             # 零宽连接符
    "\U000020E3"             # 组合封闭键帽
    "\U00002600-\U000026FF"  # 杂项符号
    "\U0000231A-\U0000231B"  # 手表、沙漏
    "\U00002934-\U00002935"  # 箭头
    "\U000025AA-\U000025AB"  # 小方块
    "\U000025FB-\U000025FE"  # 中方块
    "]+",
    flags=re.UNICODE,
)


def _strip_emoji(text: str) -> str:
    """移除文本中的 emoji 字符。"""
    return _EMOJI_RE.sub("", text)


def detect_article_type(text: str) -> str:
    """根据文本内容自动检测文章类型。"""
    text_lower = text[:2000].lower()
    scores = {}
    for atype, keywords in ARTICLE_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            scores[atype] = score
    if not scores:
        return "general"
    return max(scores, key=scores.get)


def md_to_gutenberg(md_content: str, skip_first_h1: bool = True,
                    article_type: str = "") -> str:
    """将 Markdown 转换为 WordPress Gutenberg 块格式。

    Args:
        md_content: Markdown 文本
        skip_first_h1: 是否跳过第一个 H1（用作文章标题）
        article_type: 文章类型（security/release/weekly/plugin/service/general）
                      为空时自动检测

    Returns:
        Gutenberg 块格式 HTML
    """
    if not article_type:
        article_type = detect_article_type(md_content)

    # 1. Markdown → HTML
    html = markdown.markdown(md_content, extensions=MD_EXTENSIONS)
    soup = BeautifulSoup(html, "html.parser")

    # 2. 遍历顶层元素，逐个转为 Gutenberg 块
    output: list[str] = []
    first_h1_skipped = False
    h2_count = 0

    for el in soup.children:
        if isinstance(el, NavigableString):
            text = str(el).strip()
            if text:
                output.append(_wrap_paragraph(text))
            continue

        if not isinstance(el, Tag):
            continue

        tag = el.name

        # --- 标题 ---
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            if skip_first_h1 and level == 1 and not first_h1_skipped:
                first_h1_skipped = True
                continue
            inner = _process_inline(el)
            if level == 2:
                h2_count += 1
            output.append(_make_heading_block(inner, level))

        # --- 段落 ---
        elif tag == "p":
            inner = _process_inline(el)
            if inner.strip():
                img = el.find("img")
                if img and len(el.contents) == 1:
                    output.append(_make_image_block(img))
                else:
                    output.append(_wrap_paragraph(inner))

        # --- 列表 ---
        elif tag in ("ul", "ol"):
            output.append(_make_list_block(el))

        # --- 代码块 ---
        elif tag == "pre":
            code_el = el.find("code")
            if code_el:
                lang = ""
                if code_el.get("class"):
                    for cls in code_el["class"]:
                        if cls.startswith("language-"):
                            lang = cls[9:]
                            break
                code_text = code_el.get_text()
                code_text = _escape_html(code_text)
                lang_attr = f' {{"language":"{lang}"}}' if lang else ""
                output.append(
                    f'<!-- wp:code{lang_attr} -->\n'
                    f'<pre class="wp-block-code"><code>{code_text}</code></pre>\n'
                    f"<!-- /wp:code -->"
                )
            else:
                output.append(
                    f'<!-- wp:code -->\n'
                    f'<pre class="wp-block-code"><code>{_escape_html(el.get_text())}</code></pre>\n'
                    f"<!-- /wp:code -->"
                )

        # --- 引用 ---
        elif tag == "blockquote":
            inner_parts = []
            for child in el.children:
                if isinstance(child, Tag) and child.name == "p":
                    inner_parts.append(f"<p>{_process_inline(child)}</p>")
            inner_html = "\n".join(inner_parts) if inner_parts else f"<p>{el.get_text().strip()}</p>"
            output.append(
                f'<!-- wp:quote -->\n'
                f'<blockquote class="wp-block-quote">{inner_html}</blockquote>\n'
                f"<!-- /wp:quote -->"
            )

        # --- 表格 ---
        elif tag == "table":
            output.append(_make_table_block(el))

        # --- 分隔线 ---
        elif tag == "hr":
            output.append(_SEPARATOR)

        # --- 图片（顶层） ---
        elif tag == "img":
            output.append(_make_image_block(el))

        # --- 其他：当段落处理 ---
        else:
            text = el.get_text().strip()
            if text:
                output.append(_wrap_paragraph(str(el)))

    blocks = "\n\n".join(output)

    # 3. 在 h2 之间插入分隔线（视觉分节）
    blocks = _add_h2_separators(blocks)

    # 4. 按文章类型做后处理
    blocks = _post_process_for_type(blocks, article_type, md_content)

    # 5. 最终清理：去除所有 emoji
    blocks = _strip_emoji(blocks)

    return blocks


def extract_title(md_content: str) -> str | None:
    """提取第一个 H1 标题。"""
    for line in md_content.split("\n"):
        if line.startswith("# "):
            return line.lstrip("#").strip()
    return None


# --- 分隔线常量 ---

_SEPARATOR = (
    '<!-- wp:separator -->\n'
    '<hr class="wp-block-separator has-alpha-channel-opacity"/>\n'
    '<!-- /wp:separator -->'
)


# --- 通用后处理 ---

def _add_h2_separators(blocks: str) -> str:
    """在第二个及之后的 h2 前插入分隔线，形成视觉分节。"""
    marker = "<!-- wp:heading -->"
    # 也匹配 <!-- wp:heading {"xxx"} -->（不是 h3/h4）
    h2_pattern = re.compile(r'<!-- wp:heading(?:\s+\{[^}]*\})?\s*-->\s*\n\s*<h2\b')
    parts = h2_pattern.split(blocks)
    if len(parts) <= 1:
        return blocks

    # 找到所有 h2 开始位置并在第二个起的 h2 前插入分隔线
    result_parts = []
    h2_count = 0
    pos = 0
    for m in h2_pattern.finditer(blocks):
        h2_count += 1
        result_parts.append(blocks[pos:m.start()])
        if h2_count > 1:
            result_parts.append(_SEPARATOR + "\n\n")
        pos = m.start()
    result_parts.append(blocks[pos:])
    return "".join(result_parts)


# --- 文章类型后处理 ---

def _post_process_for_type(blocks: str, article_type: str, md_content: str) -> str:
    """根据文章类型对生成的 Gutenberg 块做后处理。"""
    if article_type == "security":
        blocks = _add_security_notice(blocks)
    elif article_type == "release":
        blocks = _add_release_header(blocks, md_content)
    elif article_type == "weekly":
        blocks = _add_weekly_section_separators(blocks)
    # 所有类型：在文章末尾加分隔线收尾
    blocks = blocks.rstrip() + "\n\n" + _SEPARATOR
    return blocks


def _add_security_notice(blocks: str) -> str:
    """安全类文章：在开头插入简洁的安全通告框。"""
    notice = (
        '<!-- wp:group {"style":{"border":{"left":{"color":"var(--wp--preset--color--primary)","width":"4px","style":"solid"}},'
        '"spacing":{"padding":{"top":"16px","bottom":"16px","left":"24px","right":"24px"}}},'
        '"layout":{"type":"constrained"}} -->\n'
        '<div class="wp-block-group" style="border-left-color:var(--wp--preset--color--primary);border-left-width:4px;'
        'border-left-style:solid;padding-top:16px;padding-bottom:16px;padding-left:24px;padding-right:24px">\n'
        '<!-- wp:paragraph -->\n'
        '<p><strong>安全通告</strong> — 请相关站长及时检查并更新受影响的插件或组件。</p>\n'
        '<!-- /wp:paragraph -->\n'
        '</div>\n'
        '<!-- /wp:group -->'
    )
    return notice + "\n\n" + blocks


def _add_release_header(blocks: str, md_content: str) -> str:
    """版本发布类文章：在开头插入版本信息。"""
    ver_match = re.search(r'(\d+\.\d+(?:\.\d+)?(?:\s*(?:beta|rc|alpha)\s*\d*)?)', md_content[:500], re.IGNORECASE)
    version = ver_match.group(1) if ver_match else ""
    if not version:
        return blocks

    notice = (
        '<!-- wp:group {"style":{"border":{"left":{"color":"var(--wp--preset--color--secondary)","width":"4px","style":"solid"}},'
        '"spacing":{"padding":{"top":"16px","bottom":"16px","left":"24px","right":"24px"}}},'
        '"layout":{"type":"constrained"}} -->\n'
        '<div class="wp-block-group" style="border-left-color:var(--wp--preset--color--secondary);border-left-width:4px;'
        'border-left-style:solid;padding-top:16px;padding-bottom:16px;padding-left:24px;padding-right:24px">\n'
        '<!-- wp:paragraph -->\n'
        f'<p><strong>版本发布</strong> — 本文介绍 <strong>{version}</strong> 版本的主要变更与开发者注意事项。</p>\n'
        '<!-- /wp:paragraph -->\n'
        '</div>\n'
        '<!-- /wp:group -->'
    )
    return notice + "\n\n" + blocks


def _add_weekly_section_separators(blocks: str) -> str:
    """周报类文章：在 H3 标题前插入分隔线。"""
    h3_pattern = re.compile(r'(<!-- wp:heading \{"level":3\} -->)')
    parts = h3_pattern.split(blocks)
    if len(parts) <= 1:
        return blocks
    result = parts[0]
    h3_count = 0
    for i in range(1, len(parts), 2):
        h3_count += 1
        if h3_count > 1:
            result += "\n\n" + _SEPARATOR + "\n\n"
        result += parts[i]
        if i + 1 < len(parts):
            result += parts[i + 1]
    return result


# --- 通用区块生成 ---

def _make_heading_block(inner: str, level: int) -> str:
    """生成标题块，带 anchor ID 和 wp-block-heading class。"""
    plain_text = re.sub(r'<[^>]+>', '', inner).strip()
    anchor = re.sub(r'[^\w\u4e00-\u9fff-]', '-', plain_text).strip('-').lower()
    anchor = re.sub(r'-+', '-', anchor)

    attrs = {}
    if level != 2:
        attrs["level"] = level

    attrs_json = ""
    if attrs:
        attrs_json = f" {json.dumps(attrs, ensure_ascii=False, separators=(",", ":"))}"

    id_attr = f' id="{anchor}"' if anchor else ""

    return (
        f"<!-- wp:heading{attrs_json} -->\n"
        f'<h{level} class="wp-block-heading"{id_attr}>{inner}</h{level}>\n'
        f"<!-- /wp:heading -->"
    )


# --- 内部工具函数 ---

def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _process_inline(el: Tag) -> str:
    """处理元素内部的 HTML，保留行内格式，修正链接 target。"""
    parts = []
    for child in el.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            if child.name == "a":
                href = child.get("href", "")
                text = child.get_text()
                if href.startswith(("http://", "https://")):
                    parts.append(f'<a href="{href}" target="_blank" rel="noopener noreferrer">{text}</a>')
                else:
                    parts.append(f'<a href="{href}">{text}</a>')
            elif child.name == "img":
                parts.append(str(child))
            elif child.name == "br":
                parts.append("<br>")
            else:
                parts.append(str(child))
    return "".join(parts)


def _wrap_paragraph(inner: str) -> str:
    return f"<!-- wp:paragraph -->\n<p>{inner}</p>\n<!-- /wp:paragraph -->"


def _make_image_block(img: Tag) -> str:
    src = img.get("src", "")
    alt = img.get("alt", "")
    block_attrs = '{"sizeSlug":"large","linkDestination":"none","lightbox":{"enabled":true}}'
    return (
        f"<!-- wp:image {block_attrs} -->\n"
        f'<figure class="wp-block-image size-large"><img src="{src}" alt="{alt}"/></figure>\n'
        f"<!-- /wp:image -->"
    )


def _make_list_block(el: Tag) -> str:
    """生成列表块，支持嵌套。"""
    tag = el.name
    wp_type = "list" if tag == "ul" else 'list {"ordered":true}'

    items = []
    for li in el.find_all("li", recursive=False):
        nested = li.find(["ul", "ol"])
        if nested:
            text_parts = []
            for child in li.children:
                if isinstance(child, Tag) and child.name in ("ul", "ol"):
                    break
                text_parts.append(str(child))
            text = "".join(text_parts).strip()
            items.append(f"<li>{text}\n{_make_list_block(nested)}</li>")
        else:
            items.append(f"<li>{_process_inline(li)}</li>")

    items_html = "\n".join(items)
    return (
        f"<!-- wp:{wp_type} -->\n"
        f"<{tag}>\n{items_html}\n</{tag}>\n"
        f"<!-- /wp:list -->"
    )


def _make_table_block(el: Tag) -> str:
    """生成表格块，带 stripes 样式、固定布局和 colgroup。"""
    # 收集列数
    first_row = el.find("tr")
    col_count = 0
    if first_row:
        col_count = len(first_row.find_all(["th", "td"]))

    head_rows = []
    thead = el.find("thead")
    if thead:
        for tr in thead.find_all("tr"):
            cells = [f"<th>{_process_inline(th)}</th>" for th in tr.find_all("th")]
            head_rows.append(f"<tr>{''.join(cells)}</tr>")

    body_rows = []
    tbody = el.find("tbody")
    if tbody:
        for tr in tbody.find_all("tr"):
            cells = [f"<td>{_process_inline(td)}</td>" for td in tr.find_all("td")]
            body_rows.append(f"<tr>{''.join(cells)}</tr>")

    # 生成 colgroup（均分宽度）
    colgroup = ""
    if col_count > 0:
        width = round(100 / col_count)
        cols = "".join(f'<col style="width:{width}%" />' for _ in range(col_count))
        colgroup = f"<colgroup>{cols}</colgroup>"

    head_html = f"<thead>{''.join(head_rows)}</thead>" if head_rows else ""
    body_html = f"<tbody>{''.join(body_rows)}</tbody>" if body_rows else ""

    attrs = {"hasFixedLayout": True, "className": "is-style-stripes"}
    attrs_json = json.dumps(attrs, ensure_ascii=False)

    return (
        f'<!-- wp:table {attrs_json} -->\n'
        f'<figure class="wp-block-table is-style-stripes">'
        f'<table class="has-fixed-layout">{colgroup}{head_html}{body_html}</table></figure>\n'
        f'<!-- /wp:table -->'
    )
