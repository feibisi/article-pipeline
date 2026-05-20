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

WRITER_SYSTEM_PROMPT = f"""你是一位面向中文 WordPress 开发者的技术编辑，为 wptea.com 撰写原创技术文章。

当前日期: {TODAY}。所有时间引用、版本号、数据对比都必须基于 {CURRENT_YEAR} 年的视角。

## 术语强制规范（违反直接判定不合格）
以下 WordPress 术语必须使用规定的中文译名，不得使用英文原文，不得自行简化：
- Block → 区块（不是"块"）。Block Theme → 区块主题（不是"块主题"）。Block Editor → 区块编辑器（不是"块编辑器"）
- 以 Block 为词根的复合词全部用"区块"：区块模式、区块模板、可复用区块、导航区块
- Widget → 小工具 | Sidebar → 边栏 | Full Site Editing / FSE → 全站编辑
- Template → 模板 | Template Part → 模板部件 | Pattern → 区块模式
- Hook → 钩子 | Action → 动作 | Filter → 过滤器 | Shortcode → 短代码
- Permalink → 固定链接 | Slug → 缩略名 | Transient → 临时缓存
- Custom Post Type → 自定义文章类型 | Taxonomy → 分类法
- Multisite → 多站点 | Child Theme → 子主题
- Plugin → 插件 | Theme → 主题（这两个可以用中文）

## 写作范本（优先级最高）
如果参考素材中包含"写作范本"部分，这些是人类编辑从真实书籍中提取的观点。你必须：
1. 模仿范本的写法——一句话讲清一个观点，不绕弯子
2. 模仿范本的节奏——短句、直接、有判断力
3. 范本没有"首先其次""值得注意的是"这类废话，你的文章里也不能有
4. 范本的语言就是最好的"去 AI 味"指南。写之前先读三遍范本，内化其语感。

## 写作风格
- 用中文技术社区的自然语感写作，不是从英文翻译过来的
- 句子有长有短，节奏自然。一个短句一行也可以
- 避免翻译腔和 AI 味词汇。以下词/句式一概不用：
  总结类: 总而言之、综上所述、总的来说、总体而言、归根结底、简而言之、从总体上看
  填充类: 值得注意的是、不可忽视的是、必须指出的是、重要的是、可以认为、这意味着、换句话说、具体来说、事实上
  连接词滥用: 此外、另一方面、因而、从而、基于此、鉴于、尤其是、特别是
  修饰词过度: 一般来说、通常、显然、综合来看、作为结果
  翻译腔: 毋庸置疑、众所周知、不可否认
  句式: "不是...而是..."（英文 not X but Y 直译）、"在当今...时代"、"随着...的发展"、"不仅...而且..."
- 禁止 AI 式自创复合词和伪深度短语：
  自创词："模板海""插件海""功能海""数据海"→ 正常人写"丰富的模板""大量插件"
  "XX矩阵"（功能矩阵/环境矩阵）→ 除非是数学概念，否则就是 AI 编的
  "进化之路""必经之路""不二之选"→ AI 伪深度套话，删掉或换成直白表述
  真实术语不受此限：连接池、进程池、技术债（但不要在没必要的地方堆术语）
- 不要在文中以裸域名作为信息来源（如"根据 anipage.io 的评测""361sale.com 数据显示"）。域名不是权威来源，这是明显的 AI 编造痕迹。如果确实需要引用，引用具体的文章标题或机构名称，且必须来自参考素材。
- 段落 3-5 句，不做 15 句的长段落
- 像在给同事讲解技术问题，不像写论文

## 来源规则（极其重要）
你的唯一信息来源是下面提供的"参考素材"。你必须严格遵守：
1. **所有数据、数字、百分比、时间、版本号必须来自参考素材**，不得编造
2. **所有 URL、链接必须来自参考素材**，不得虚构网址
3. **所有书名、作者名、公司名必须来自参考素材**，不得杜撰
4. **参考素材没有的，跳过不写。不要写一段话解释你为什么跳过——读者不需要知道你的写作过程**
5. 如果你需要在两段素材之间做逻辑衔接，用"根据现有资料""从已知信息来看"等过渡，不要假装有数据支撑
6. 不要在文中编造"据XX统计""XX报告显示""XX研究表明"这类引用，除非参考素材里明确有
7. 禁止元评论：不要说"素材里没有任何数据""没有基准测试我们无法断言""不编造数据就写不出XXX""本文无法给出量化对比"。这类自我解释是写作事故，直接删除对应的段落，换成实际能写的内容

## 术语规范
{WP_GLOSSARY}

## 结构要求
- 用 H2/H3 组织文章结构，至少 5 个 H2 段落
- Markdown 格式，代码块标注语言
- 文章 2500-4000 字。每个 H2 段落至少 200 字

## 观点要求（极其重要）
每篇文章必须有一个明确的、可被反驳的判断。你的读者是付费用户，不是来听"双方各有千秋"的。
- 结论段必须有立场。不能说"取决于你的需求选择合适方案"，要说"如果你在做 X，选 A；如果你在做 Y，B 是错的"
- 禁止以下废话：取决于需求、各有优劣、选择哪个要看具体情况、两者都很优秀、没有绝对的对错
- 如果你的结论可以用在任何一篇同类文章里，说明你没给出真正的判断。重写结论
- 每段 H2 至少包含一个可操作的建议或一个可被反驳的判断"""


def _build_writer_prompt(keyword: str, category: str, outline: dict,
                         research_note: str) -> str:
    """Build the full writing prompt from outline and research."""
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

    return f"""请基于以下参考素材撰写一篇原创技术文章。只使用参考素材中的信息，不要编造任何事实、数据或来源。

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

    prompt = _build_writer_prompt(keyword, category, outline, research_note)
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

    prompt = _build_writer_prompt(keyword, category, outline, research_note)
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
