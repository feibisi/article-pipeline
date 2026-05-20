"""Article writing via DeepSeek API (Anthropic-compatible endpoint)."""
import os
import re
from datetime import date
import requests
import yaml


def _load_config():
    config_path = os.path.expanduser("~/.config/article-pipeline/config.yaml")
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
            return config if isinstance(config, dict) else {}
    except (FileNotFoundError, yaml.YAMLError):
        return {}


# WordPress 中文术语速查（核心高频词）
WP_GLOSSARY = """WordPress 中文术语规范：
- Dashboard → 仪表盘 | Admin Bar → 工具栏 | Toolbar → 工具栏
- Widget → 小工具 | Sidebar → 边栏 | Menu → 菜单
- Site Editor → 站点编辑器 | Block Editor → 区块编辑器
- Block → 区块 | Pattern → 区块模式 | Template → 模板
- Template Part → 模板部件 | Reusable Block → 可复用区块
- Full Site Editing (FSE) → 全站编辑 | theme.json → theme.json
- Query Loop → 查询循环 | Group → 组块 | Row/Stack → 行/堆叠
- Navigation Block → 导航区块 | Post Excerpt → 文章摘要
- Featured Image → 特色图片 | Cover → 封面
- Custom Post Type → 自定义文章类型 | Taxonomy → 分类法
- Category → 分类 | Tag → 标签 | Term → 项目
- Permalink → 固定链接 | Slug → 缩略名
- Plugin → 插件 | Theme → 主题 | Hook → 钩子
- Action → 动作 | Filter → 过滤器 | Shortcode → 短代码
- REST API → REST API | WP-CLI → WP-CLI
- Cron → 计划任务 | Transient → 临时缓存
- Multisite → 多站点 | Network Admin → 网络管理
- Child Theme → 子主题 | Parent Theme → 父主题
- Post Type → 文章类型 | Post Status → 文章状态
- Customizer → 自定义器 | Site Health → 站点健康"""

TODAY = date.today().isoformat()  # e.g. 2026-05-20
CURRENT_YEAR = str(date.today().year)

WRITER_SYSTEM_PROMPT = f"""你是面向中文 WordPress 开发者的技术编辑，为 wptea.com 撰写原创文章。
当前日期: {TODAY}。所有时间引用、版本号、数据必须基于 {CURRENT_YEAR} 年视角。

## 写作范本
你将收到一组"写作范本"——人类编辑从书籍中提取的观点。它们是你的风格老师。
1. 先读范本，感受节奏：简洁、有判断、一句话讲清一个观点。
2. 用范本的语感写文章。范本没有废话，你也不能有。
3. 范本是你最好的"怎么写"指南。风格规则由范本示范，不由文字规定。

## 来源规则
唯一信息来源是"参考素材"。编造数据、URL、书名、人名、公司名是写作事故。
- 所有数字、百分比、时间、版本号必须来自参考素材
- 不引用裸域名（"根据 xxx.com"）。引用文章标题或机构名称
- 参考素材没有的，跳过不写。禁止元评论（"素材没有数据""本文无法给出量化对比"）

## 术语
{WP_GLOSSARY}

## 输出
- 2500-4000 字 Markdown，H2/H3 结构，至少 5 个 H2 段落
- 结论必须有明确立场。禁止"取决于需求""各有优劣""两者都很优秀"
- 如果结论可以用在任何同类文章里，重写结论"""


def _build_writer_prompt(keyword: str, category: str, outline: dict,
                         research_note: str, writing_samples: list[dict] | None = None) -> str:
    """Build the full writing prompt from outline and research."""
    # Writing samples as few-shot style templates
    samples_block = ""
    if writing_samples:
        sample_texts = []
        for s in writing_samples[:4]:
            claim = s.get("claim", "")
            claim_type = s.get("type", "")
            quality = s.get("quality", "")
            if claim:
                sample_texts.append(f"[{quality}级|{claim_type}] {claim}")
        if sample_texts:
            samples_block = ("## 写作范本（读三遍再动笔）\n"
                             "以下是人类编辑从书籍中提取的观点。每一条都是好文字的范本——简洁、有判断、一句话讲清一个观点。\n"
                             "你的文章必须匹配这种语感和节奏。不要写成教科书。\n\n"
                             + "\n\n".join(sample_texts) + "\n\n")

    sections_text = ""
    for i, sec in enumerate(outline.get("sections", [])):
        sections_text += f"\n## {sec.get('heading', '')}\n"
        for pt in sec.get("points", []):
            sections_text += f"- {pt}\n"

    title = keyword
    if outline.get("titles"):
        title = outline["titles"][0].get("text", keyword)

    # If research note is too sparse, warn the model
    source_note = research_note[:3000]
    if len(source_note) < 200:
        source_note += ("\n\n[注意：参考素材较少。请仅基于已有素材写作，"
                        "不要编造数据、URL、书名或统计数字。不确定的地方直接说'目前没有公开数据']")

    return f"""{samples_block}请基于以下参考素材撰写一篇原创技术文章。只使用参考素材中的信息，不要编造任何事实、数据或来源。

## 文章信息
- 标题: {title}
- 关键词: {keyword}
- 核心论点: {outline.get('core_argument', '')}

## 段落结构
{sections_text}

## 参考素材（这是你唯一的信息来源）
{source_note}

## 输出要求
- 全文 2500-4000 字。不要少于 2000 字。每个 H2 段落写充实，不要几句话就换段
- 直接输出 Markdown 正文，不要加"好的""以下是文章"等前缀
- 文中的数据、URL、书名、人名必须能在参考素材中找到对应条目
- 参考素材没有的信息，宁可跳过也不编造"""


def _extract_samples(research_note: str) -> list[dict]:
    """Extract writing samples from the research note's 写作范本 section."""
    import re as _re
    samples = []
    # Match patterns like: "1. [B级|technique] claim text"
    pattern = _re.findall(r'\d+\.\s*\[([AB])级\|(\w+)\]\s*(.+?)(?=\n\d+\.\s*\[|$)', research_note, _re.DOTALL)
    for quality, ctype, claim in pattern:
        samples.append({"quality": quality, "type": ctype, "claim": claim.strip()})
    return samples


def _call_messages_api(base_url: str, api_key: str, model: str,
                       system_prompt: str, user_prompt: str,
                       max_tokens: int = 4096) -> dict:
    try:
        resp = requests.post(
            f"{base_url}/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}]
            },
            timeout=180
        )
        resp.raise_for_status()
        data = resp.json()

        text_parts = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        content = "\n".join(text_parts)

        return {
            "article": content,
            "model": data.get("model", model),
            "tokens": data.get("usage", {})
        }
    except requests.ConnectionError:
        return {"error": "api_unreachable",
                "message": f"Cannot connect to {base_url}"}
    except requests.Timeout:
        return {"error": "api_timeout", "message": "Request timed out after 180s"}
    except requests.RequestException as e:
        return {"error": "request_failed", "message": str(e)}
    except (KeyError, IndexError, TypeError) as e:
        return {"error": "bad_response", "message": str(e)}


EDITOR_SYSTEM_PROMPT = f"""你是一位严苛的中文技术编辑。你的任务是对文章做最后润色——砍废话、强化判断、让文章有骨头。

当前日期: {date.today().isoformat()}。

## 术语修正（优先级最高）
- "块编辑器" → "区块编辑器" | "块主题" → "区块主题" | "以块为" → "以区块为"
- "块" 单独指代 block 概念时 → "区块"
- 英文术语必须替换为中文：Block→区块, FSE→全站编辑, Hook→钩子, Pattern→区块模式, Shortcode→短代码

## 润色规则
1. 检查结论段。如果没有明确立场（"取决于需求""各有优劣""两者都很优秀"），直接重写，给出具体场景下的明确选择
2. 砍掉说了等于没说的句子
3. 合并重复段落
4. 客套话直接删
5. 砍掉所有元评论——"素材里没有数据""本文无法给出量化对比""不编造数字就写不出"。读者不需要听你解释写作过程。如果没数据，直接跳过这个角度，写其他有内容的东西。
5. 不要加新的事实、数据或引用
6. 输出处理后的完整 Markdown"""


def polish_article(article: str, keyword: str = "") -> dict:
    """Editorial polish pass — tighten language, strengthen conclusions."""
    config = _load_config()
    ds_config = config.get("deepseek", {})
    api_key = os.environ.get("AP_DS_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "missing_api_key"}

    base_url = ds_config.get("base_url", "https://api.deepseek.com/anthropic")
    model = ds_config.get("model", "deepseek-v4-pro")

    polish_prompt = f"""请对下面这篇关于"{keyword}"的文章做编辑润色。

## 润色重点
- 检查结论是否有明确立场。如果最后是"两者各有千秋"式废话，直接砍掉重写，给出具体场景下的明确选择
- 砍掉没有信息量的句子
- 合并重复段落

## 原文
{article}"""

    return _call_messages_api(base_url, api_key, model,
                              EDITOR_SYSTEM_PROMPT, polish_prompt, 4096)


def write_article(keyword: str, category: str, outline: dict,
                  research_note: str) -> dict:
    config = _load_config()
    ds_config = config.get("deepseek", {})

    api_key = os.environ.get("AP_DS_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "missing_api_key",
                "message": "Set AP_DS_API_KEY or ANTHROPIC_API_KEY env var"}

    base_url = ds_config.get("base_url", "https://api.deepseek.com/anthropic")
    model = ds_config.get("model", "deepseek-v4-pro")

    if category == "book-knowledge":
        model = ds_config.get("model_deep", "deepseek-v4-pro")

    samples = _extract_samples(research_note)
    prompt = _build_writer_prompt(keyword, category, outline, research_note, samples)
    result = _call_messages_api(base_url, api_key, model,
                                WRITER_SYSTEM_PROMPT, prompt,
                                ds_config.get("max_tokens", 4096))

    # Polish is DISABLED — GLM-5.1 writes clean enough. Polish was eating 60% of content.
    # To re-enable: uncomment the block below

    # Hard terminology fix — model won't do it, so we do it
    if "error" not in result:
        result["article"] = _fix_terminology(result["article"])

    return result


def _fix_terminology(text: str) -> str:
    """Post-process: enforce WP Chinese terminology that the model ignores."""
    # Block terms — use negative lookbehind to avoid double-replacing 区块→区区块
    text = re.sub(r'(?<!区)块编辑器', '区块编辑器', text)
    text = re.sub(r'(?<!区)块主题', '区块主题', text)
    text = re.sub(r'(?<!区)以块为(单位|核心|基础|单元|内容)', r'以区块为\1', text)
    # English terms that should be Chinese
    text = re.sub(r'\bFull Site Editing\b', '全站编辑', text)
    text = re.sub(r'\bFSE\b', '全站编辑', text)
    return text


def write_article_claude(keyword: str, category: str, outline: dict,
                         research_note: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "missing_api_key",
                "message": "ANTHROPIC_API_KEY env var not set"}

    samples = _extract_samples(research_note)
    prompt = _build_writer_prompt(keyword, category, outline, research_note, samples)
    return _call_messages_api("https://api.anthropic.com", api_key,
                              "claude-sonnet-4-6",
                              WRITER_SYSTEM_PROMPT, prompt, 4096)


REVISION_SYSTEM_PROMPT = f"""你是一位严谨的中文技术编辑。你的任务是根据审稿反馈修改已有文章，而不是重写。

当前日期: {date.today().isoformat()}。

## 修改规则
1. 只修改被指出的问题，不要改动没有问题的段落
2. 保持原文的写作风格和语气
3. 如果被指出 AI 味太重，用更自然、口语化的中文替换 flagged 词汇
4. 如果被指出事实未核实，删除或替换为参考素材中的内容
5. 如果被指出编造内容（URL、数据、人名），删除编造部分
6. 保持文章结构不变（H2/H3 标题、段落划分）
7. 直接输出修改后的完整 Markdown，不要加前缀说明

## 术语规范
{WP_GLOSSARY}"""


def _build_revision_prompt(keyword: str, original_article: str,
                           suggestions: list[dict],
                           research_note: str = "") -> str:
    issues_text = ""
    for i, s in enumerate(suggestions, 1):
        issues_text += f"\n{i}. [{s.get('priority', 'medium')}] {s.get('category', '')}"
        issues_text += f"\n   问题: {s.get('issue', '')}"
        issues_text += f"\n   修改: {s.get('fix', '')}"

    source_section = ""
    if research_note:
        source_section = f"\n## 参考素材（修改时以此为准）\n{research_note[:3000]}"

    return f"""请根据以下审稿反馈修改文章。只改被指出的问题，保持其他内容不变。

## 文章主题: {keyword}

## 审稿反馈
{issues_text}
{source_section}

## 原文（请在此基础上修改）
{original_article}"""


def write_article_with_feedback(keyword: str, category: str, outline: dict,
                                 research_note: str, original_article: str,
                                 suggestions: list[dict]) -> dict:
    """Revise an article based on structured review feedback."""
    config = _load_config()
    ds_config = config.get("deepseek", {})

    api_key = os.environ.get("AP_DS_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "missing_api_key",
                "message": "Set AP_DS_API_KEY or ANTHROPIC_API_KEY env var"}

    base_url = ds_config.get("base_url", "https://api.deepseek.com/anthropic")
    model = ds_config.get("model", "deepseek-v4-pro")

    prompt = _build_revision_prompt(keyword, original_article, suggestions, research_note)
    return _call_messages_api(base_url, api_key, model,
                              REVISION_SYSTEM_PROMPT, prompt, 4096)


HUMAN_FEEDBACK_SYSTEM_PROMPT = """你是一位严谨的中文技术编辑。根据审稿人的具体反馈逐条修改文章。

修改规则:
1. 逐条处理反馈中的每个问题，不要遗漏
2. 只修改被指出的问题，保持其他内容不变
3. 如果反馈说"太浅"，就加深那段的论证或补具体例子
4. 如果反馈说"AI味"，就改得更口语、更直接
5. 如果反馈说"结论弱"，就强化判断，给出明确立场
6. 保持原文结构，不要推到重写
7. 直接输出修改后的完整 Markdown"""


def revise_with_human_feedback(keyword: str, article: str,
                                feedback_text: str,
                                research_note: str = "") -> dict:
    """Revise article based on human reviewer's specific feedback."""
    config = _load_config()
    ds_config = config.get("deepseek", {})

    api_key = os.environ.get("AP_DS_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "missing_api_key"}

    base_url = ds_config.get("base_url", "https://api.deepseek.com/anthropic")
    model = ds_config.get("model", "deepseek-v4-pro")

    source = f"\n\n参考素材:\n{research_note[:2000]}" if research_note else ""

    prompt = f"""请根据以下审稿反馈修改文章。

文章主题: {keyword}

## 审稿反馈
{feedback_text}
{source}

## 原文（请在此基础上修改）
{article}"""

    return _call_messages_api(base_url, api_key, model,
                              HUMAN_FEEDBACK_SYSTEM_PROMPT, prompt, 8192)
