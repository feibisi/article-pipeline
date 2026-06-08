"""Article writing via DeepSeek API (Anthropic-compatible endpoint)."""
from article_pipeline.config import load_config
from article_pipeline.style import render_style_block
import os
import re
from datetime import date
import requests
import time
import yaml



# Content Trust Tiers
# TIER_INTERNAL: Writer has domain knowledge; LLM can fill gaps and use hypothetical scenarios.
# TIER_EXTERNAL: Facts come from external products/services; LLM must ONLY write from confirmed sources.
TIER_INTERNAL_CATEGORIES = frozenset({
    "tutorial", "opinion", "comparison", "listicle", "guide",
    "troubleshooting", "beginner", "trend", "thought-leadership",
    "editorial", "news", "wp-tech", "book-knowledge",
})
TIER_EXTERNAL_CATEGORIES = frozenset({
    "product-launch", "announcement", "brand-marketing",
    "case-study", "tool-review", "resource-roundup",
    "soft-article", "marketing",
})


def get_trust_tier(category: str) -> str:
    """Return the content trust tier for a given category."""
    if not category:
        return "TIER_INTERNAL"
    cat_lower = category.lower().strip()
    if cat_lower in TIER_EXTERNAL_CATEGORIES:
        return "TIER_EXTERNAL"
    return "TIER_INTERNAL"


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

## 写作原则（来自中文写作经典，每条都是硬规则）
以下原则来自中文写作领域的最佳实践。它们不是建议，是你在每一段都要遵守的规则。

1. **放下"写好"的包袱**。一旦有"好好写"的意识，书写就会停滞。专注于"有用"而不是"好看"。读者关掉页面只有一个原因：没得到有用的东西。
2. **具体 > 抽象**。沈从文教写作：不要用"美丽"形容花，写花在你心里引起的具体感受。抽象形容词是懒惰的写作。写"侧边栏加载慢"不要写"性能存在问题"。
3. **文章九成靠素材**。素材三要素：独立的事件、情节、数字。没有素材支撑的观点是空话。所有数字、百分比、版本号必须来自参考素材。
4. **心里有具体读者**。所有文章一定有"你希望读的人"。不确定读者时，选一个具体的——比如"正在搭建第一个区块主题的 WP 开发者"。不要写给所有人看。
5. **先写后编**。先把核心观点快速倒出来，再回头润色。不要在写第一段时就追求完美——你会在那里卡住，最后写出废话。
6. **文字的力量在感知唤起**。好的技术文章不传递信息量，传递"能用起来"的感觉。写代码示例要让人能复制粘贴运行，写原理要让人能讲给别人听。
7. **知识写作的核心是转化**。将专业信息转化为读者能理解、感兴趣的内容。不是翻译文档，不是堆砌知识点。每写一段问自己：读者为什么要关心这个？
8. **一个观点一句话**。简洁不等于短——简洁等于每个句子都有存在的理由。砍掉所有可以删掉而不影响理解的词。

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
- 把主题讲清楚为止。不设字数上下限。如果 1500 字讲清楚了就写 1500 字。不要为凑字数重复解释或硬塞例子。
- 结论必须有明确立场。禁止"取决于需求""各有优劣""两者都很优秀"
- 如果结论可以用在任何同类文章里，重写结论"""


def _genre_rules(category: str, tier: str = "TIER_INTERNAL") -> str:
    """Return genre-specific hard writing rules derived from Chinese prose principles."""
    if tier == "TIER_EXTERNAL":
        common = (
            '## 严格写作准则（外部产品文章 —— 所有事实必须来自参考素材）\n\n'
            '- **信息来源红线**：每一句话涉及的事实、数字、URL、功能名、价格、日期都必须来自参考素材。素材没有的，你就不写。\n'
            '- **缺口优于造假**：不确定的事情直接跳过。少写一个段落不扣分，编造一个数据整篇文章废掉。写"该功能详情将在后续更新中公布"而不是猜一个解释。\n'
            '- **禁止假设场景**：严禁编造假设场景、用户故事、使用案例——除非参考素材中明确描述了这些场景。不要写"假设你正在搭建一个..."除非素材里有。\n'
            '- **功能与特性**：只能写素材中确认的功能。不能猜测"应该支持""可能会有"——素材没写就不是你的工作去补。\n'
            '- **例子不强制**：如果某个段落没有足够素材支撑具体例子，可以写纯解释性段落。解释必须基于素材，不是你的推测。\n'
            '- **禁止 Mermaid 图**：外部产品文章不插入技术架构图或流程图。\n'
            '- **禁止引用不存在的图表**：不要写"从这张图""下图展示了"等文字。\n'
            '- 写作姿态：像跟你最聪明但没耐心的朋友解释一件事。\n'
            '- 一句话一个意思。不用从句嵌套。\n'
            '- 不用"赋能""闭环""抓手""天花板""底层逻辑"等管理黑话。\n'
            '- 段落之间自然过渡，不用"此外""另外""与此同时"衔接。\n'
        )
    else:
        common = (
            '- 写作姿态：像跟你最聪明但没耐心的朋友解释一件事。他知道你什么意思所以不铺垫。不需要文采，需要精准。写到一半有三段说同一件事，删两段。\n'
            '- 全篇——不超过3个。能用句号的地方用句号，解释说明用冒号，转折用逗号。写完后数一遍——超过3个就把多余的删掉。正常人写一篇东西不会用超过两次破折号。\n'
            '- 一句话一个意思。不用从句嵌套。每段不超过3句话，超过就拆。\n'
            '- 数据后面必须跟一句解释，说明这个数字意味着什么。\n'
            '- 教程和案例研究类文章可以用假设场景说明问题。产品发布、品牌营销、公告类文章严禁编造假设场景——只写素材中确认的事实。\n'
            '- 素材中未确认的数据、数字、时间、URL、地址、流程细节——直接跳过不写。不需要填满每个段落。不确定的事情说"目前未公布"比编一个具体数字好一百倍。\n'
            '- 不用"赋能""闭环""抓手""天花板""底层逻辑"等管理黑话。\n'
            '- 段落之间不用"此外""另外""与此同时"衔接，让内容自然过渡。\n'
            '- 每个H2段落必须有至少一个具体的例子、数字、或代码片段。不能全段都是解释。这些例子和数字必须来自参考素材，不能编造。如果素材不够支撑一个完整的H2段落，宁可不写这个段落。\n'
            '- 技术教程和系统架构类文章可以插入Mermaid图。产品发布和营销类文章不要插入Mermaid图——没有图比编造图更好。\n'
            '- 不要在文中引用不存在的图表。不要写"从这张图""下图展示了"等指向图表的话，除非确实插入了图。\n'
        )

    rules = {
        "tutorial": '''## 教程写作规则（必须遵守）
- 每节用一个具体场景或问题开头("你想在文章里嵌入一个表单，但 WordPress 默认不让插 PHP")，不用概念定义开头("Shortcode 是 WordPress 提供的一种宏替换机制")。
- 先给例子，再解释原理。读者是来解决问题的，不是来上课的。
- 不用"首先...其次...最后..."结构。用自然的时间顺序或因果顺序。
- 代码块后面必须跟一句人话解释这段代码做了什么。
- 每一步操作都要说明"如果不这样做会怎样"——教避坑比教操作更有用。
- 涉及多组件交互时（请求→Nginx→PHP→MySQL→返回），必须配一张 sequenceDiagram 或 graph TD。
''',
        "opinion": '''## 观点写作规则（必须遵守）
- 开头50字内亮出你的判断。不要铺垫背景，不要"随着WordPress的发展"。
- 至少用一个对比来制造张力："X不是Y，而是Z"或"表面上看是A，实际是B"。
- 结论必须有明确立场。不许说"取决于具体情况"或"各有优劣"。选一边站。
- 指出对立观点的一个具体错误，用实例说明它在哪里不成立。
- 用短句表达判断。"全站编辑就是WordPress的未来"比"从多个维度来看，全站编辑似乎代表了WordPress发展的某种方向"强一百倍。
''',
        "comparison": '''## 对比写作规则（必须遵守）
- 必须有一个对比框架——表格、选择维度、或决策树。不能各自介绍完就算对比。
- 每个维度两边同时说，不要介绍完A再介绍B。
- 给出明确建议："大多数情况下选X"。不说的，读者看完还是不知道怎么选。
- 用具体数字说明差异("TTFB差距约200ms")，不用"更快""更好"这种空话。
- 指出每种方案不适合的场景。没有完美的方案，不说缺点等于不诚实。
''',
        "listicle": '''## 清单写作规则（必须遵守）
- 10条之间必须有逻辑递进关系——从最基础到最进阶，或从最常见到最冷门。不是10个段落拼在一起。
- 每条 = 一个核心观点 + 一个具体实例 + 一个可执行的操作。缺一不可。
- 最重要的排前面。不需要为了"逻辑顺序"把最重要的藏在第9条。
- 条与条之间有关联词："这一点和上一条配合使用效果最好"。
''',
        "guide": '''## 指南写作规则（必须遵守）
- 每节解决一个问题。如果本节不解决任何问题，删掉。
- 先告诉你为什么这件事重要(具体后果，不是"在当今数字化时代")，再告诉你怎么做。
- 给出检查清单——读者怎么知道自己做对了？
- 必须有"常见错误"段落——列出新手最容易犯的2-3个错。
''',
        "troubleshooting": '''## 排错指南写作规则（必须遵守）
- 先给症状后给解药："你看到白屏/超时/500错误"——让读者一秒判断这篇文章是不是他的问题。
- 按排查顺序写：先检查最简单的（重启/缓存/日志），再深入（配置/代码/数据库）。
- 每步给诊断命令和预期输出（ssh 执行什么，看到什么说明正常，看到什么说明有问题）。
- 最后的方案是永久修复，不只是临时绕过。不说"禁用插件就好了"，说"升级到X版本并添加Y配置"。
''',
        "tool-review": '''## 工具评测写作规则（必须遵守）
- 开头明确评测标准（功能、性能、价格、易用性、生态），不是想到哪写到哪。
- 必须实测过。没有实测过的功能不能说"支持"，只能说"文档声称支持"。
- 每个优缺点带具体证据（截图数据、操作耗时、兼容性问题），不用"体验很好"这种空话。
- 给出"适合谁/不适合谁"——没有任何工具适合所有人。
''',
        "case-study": '''## 案例拆解写作规则（必须遵守）
- 先给结果（加载时间从3s→0.8s，流量增长40%），再讲过程。读者先知道值不值得读。
- 用第一人称或具体项目名。"某电商站"不如"一个日活3000的WooCommerce店铺"。
- 讲踩坑过程：试了什么、为什么失败、怎么想通的。成功的案例不涨经验，失败的案例才长。
- 结尾给可复用的方法论，不只是"这次我们做了什么"。
''',
        "beginner": '''## 新手入门写作规则（必须遵守）
- 假设读者什么术语都不懂。第一次出现的专业词必须用一句话解释。
- 每一步带屏幕截图描述或精确的菜单路径（"左侧菜单 → 设置 → 常规"）。
- 给"最简可用"路径：读者15分钟内能看到结果，而不是读完3000字才迈出第一步。
- 不假设读者有命令行/VPS/Git基础。如果需要，另开一节"前置准备"。
''',
        "trend": '''## 行业趋势写作规则（必须遵守）
- 开头用具体数据锚定趋势（增长率、市场份额变化、采用率），不用"近年来"开头。
- 区分事实和判断。"React份额从38%降到33%"是事实，"React正在衰落"是你的判断。
- 至少引用两个独立数据源，标注来源和时间。数据超过两年的要说明为什么仍有参考价值。
- 趋势推演给三个方向（乐观/基准/悲观），不说"未来肯定会怎样"。
''',
        "resource-roundup": '''## 资源推荐写作规则（必须遵守）
- 每条推荐说明为什么入选（解决了什么具体问题），不是列名称和链接。
- 免费/付费标注清楚。隐藏收费的资源标注为"免费试用"是不诚实的。
- 同类资源放在一起比较优劣，不做成"10个最好的X"的扁平清单。
- 给出学习路径：先看哪个、再看哪个、哪两个配合效果最好。
''',
        "marketing": '''## 营销文案写作规则（必须遵守）
- 开头用目标读者的痛点或渴望开头，不用产品介绍开头。读者只关心"这对我有什么用"。
- 一个核心卖点贯穿全文，不要堆功能列表。十个功能不如一个能记住的场景。
- 用具体数字建立信任（"已有2300+开发者使用"），没有数据用用户证言。
- 结尾有明确行动号召（CTA）：不只是"了解更多"，是"现在下载，15分钟搭好第一个项目"。
''',
        "product-launch": '''## 产品发布写作规则（必须遵守）
- 第一段回答四个问题：这是什么、给谁用、解决什么问题、和现有方案有什么不同。
- 给时间线：现在能用什么、接下来的版本有什么、什么时候发布。
- 定价和获取方式必须写清楚。不标价的产品发布等于没发布。
- 至少一个使用场景的具体描述：用户从打开到完成任务的完整路径。
''',
        "announcement": '''## 事务通知写作规则（必须遵守）
- 第一行给结论（"X月X日起，Y服务将停止支持"），不铺垫。
- 受到影响的人明确列出（"使用旧版API的用户"），不在影响范围的也明确说（"个人博客用户不受影响"）。
- 时间线用列表形式：生效日期、过渡期截止日期、旧方案停止日期。
- 给替代方案的具体路径，不是"请联系客服"，是"迁移到新版API只需改一行endpoint地址"。
''',
        "news": '''## 新闻快讯写作规则（必须遵守）
- 标题包含核心事实（谁做了什么/发生了什么），不是点击诱导。
- 第一段涵盖5W：谁、什么事、什么时候、在哪、为什么重要。
- 正文按重要性递减排列细节，不是按时间线。最重要的细节在前300字。
- 引用来源和官方声明原文。转述不如直接引用。
''',
        "brand-marketing": '''## 品牌营销写作规则（必须遵守）
- 不是卖产品，是建认知。读者看完不需要下单，但下次听到你名字会觉得"这帮人懂行"。
- 钩子 = 行业里一个被忽视的问题。不是"X很重要"，是"大多数人做X时都犯了这个错"。
- 正文至少60%讲行业问题和解决方案，只有最后一段可以提你自己——而且是以"比如"的形式，不是"所以你应该用我们"。
''',
        "soft-article": '''## 软文写作规则（必须遵守）
- 伪装成搜索型文章。读者前三秒不能察觉是广告。如果标题或第一段暴露了，这篇就废了。
- 正文 = 90%的技术分析 + 10%的自然引导。技术部分要覆盖所有主流方案（包括竞品），公平客观。
- 结论段只提一次你的产品，作为"另一个值得关注的选项"。不给链接，不给定价，不列功能——只给一个场景描述。
- 如果读者看完觉得"这篇文章帮我搞清楚了问题，顺便知道了X"，这篇就成功了。如果读者看完觉得被推销了，就失败了。
''',
        "thought-leadership": '''## 思想领导力写作规则（必须遵守）
- 立场必须鲜明且可能得罪人。如果所有人都同意你的判断，这篇就不值得写。
- 钩子 = 一个被普遍接受的观点 + 为什么它可能是错的（或被低估了）。
- 支撑判断至少需要两个独立源——自己的数据、行业报告、具体案例、官方变更记录。不是一个专家说。
- 结论不要说"我们需要更多讨论"——你的整篇文章就是你的答案。
''',
        "editorial": '''## 社论/评论写作规则（必须遵守）
- 对最近的事件表态。第一段说清楚发生了什么 + 你为什么关注。
- 立场必须鲜明。哪怕你的判断不完美，比"双方都有道理"好十倍。
- 至少指出一次对立观点的具体错误——在哪儿、什么事实可以证伪它。
- 结尾呼吁一个具体行动（不只是"大家要重视"——谁、做什么、怎么开始）。
''',
    }

    cat_lower = category.lower().strip()
    # Exact match first — prevents "marketing" from matching "brand-marketing"
    if cat_lower in rules:
        return "### 写作规则（以下规则必须严格遵守，违规将被拒绝）\n\n" + common + rules[cat_lower]
    # Fallback: substring match for compound categories
    for key, rule in rules.items():
        if key in cat_lower or cat_lower in key:
            return "### 写作规则（以下规则必须严格遵守，违规将被拒绝）\n\n" + common + rule
    # Default: guide rules
    return "### 写作规则（以下规则必须严格遵守，违规将被拒绝）\n\n" + common + rules["guide"]


def _build_writer_prompt(keyword: str, category: str, outline: dict,
                         research_note: str, writing_samples: list[dict] | None = None,
                         tier: str = "TIER_INTERNAL",
                         style_overrides: dict | None = None) -> str:
    """Build the full writing prompt from outline and research."""
    # Writing craft examples — illustrate the rules, don't replace them
    samples_block = ""
    if writing_samples:
        sample_texts = []
        for s in writing_samples[:3]:
            claim = s.get("claim", "")
            if claim:
                sample_texts.append(f"- {claim}")
        if sample_texts:
            samples_block = ("## 语感参考（这些句子来自中文写作经典，体会节奏和判断力）\n"
                             + "\n".join(sample_texts) + "\n\n")

    sections_text = ""
    for i, sec in enumerate(outline.get("sections", [])):
        sections_text += f"\n## {sec.get('heading', '')}\n"
        for pt in sec.get("points", []):
            sections_text += f"- {pt}\n"

    title = keyword
    if outline.get("titles"):
        title = outline["titles"][0].get("text", keyword)

    # EXTERNAL articles get more research context
    trunc_limit = 8000
    source_note = research_note[:trunc_limit]
    if len(source_note) < 200:
        source_note += ('\n\n[素材较少。只写素材中确认的事实，不编造数据或来源。'
                        '不确定的直接说"目前没有公开数据"。]')

    # Add fact-grading instructions if the research note uses [已确认]/[需确认] tags
    has_confirmed = '[已确认]' in source_note
    has_pending = '[需确认]' in source_note
    if has_confirmed or has_pending:
        fact_guide = '\n\n## 事实分级规则（严格遵守）\n'
        if tier == "TIER_EXTERNAL":
            fact_guide += '**铁律：你正在写外部产品文章，所有事实必须逐字来自用户确认的材料。**\n'
        fact_guide += '- `[已确认]` — 用户亲自确认或代码/文档中有明确记录的事实。可以引用，不需要修饰。\n'
        fact_guide += '- `[需确认]` — 用户尚未确认的点。**禁止在正文中使用这些信息。** 只能在用户确认后才能写入文章。\n'
        fact_guide += '- 没有标记的事实块 → 视为 `[需确认]`，不要写进文章。\n'
        if tier == "TIER_EXTERNAL":
            fact_guide += '- **记住**：整段素材都是 `[需确认]` 的段落必须跳过。用"该功能详情将在后续更新中公布"表示，不要用猜测填满。\n'
        else:
            fact_guide += '- 如果某个段落的所有素材都是 `[需确认]`，跳过这个段落，不要用猜测填满它。\n'
        source_note += fact_guide

    # Build claim + audience block — these are the article's anchor
    claim = outline.get("claim", {})
    audience = outline.get("audience", "") or claim.get("audience", "")
    hook = outline.get("hook", "")
    notification = outline.get("notification", {})

    anchor_parts = ["## 这篇文章的主张（你的每一段都必须服务于论证这个主张）"]

    if notification and notification.get("what_changed"):
        anchor_parts.append(f"\n### 通知要点（告知型文章——直奔主题）")
        anchor_parts.append(f"- 什么变了: {notification.get('what_changed', '')}")
        anchor_parts.append(f"- 影响谁: {notification.get('who_affected', '')}")
        anchor_parts.append(f"- 要做什么: {notification.get('what_to_do', '')}")
        anchor_parts.append(f"- 生效时间: {notification.get('effective_date', '')}")
        anchor_parts.append(f"\n文章第一行必须说清什么变了。不铺垫。")

    if hook:
        anchor_parts.append(f"\n### 钩子\n文章开头第一句话必须从这里出发：{hook}\n不要铺垫背景，不要'随着XX的发展'。直接扎进去。")

    if claim:
        anchor_parts.append(f"- 为什么这件事重要: {claim.get('why_matters', '')}")
        anchor_parts.append(f"- 大多数人的误解: {claim.get('common_misunderstanding', '')}")
        anchor_parts.append(f"- 你的核心判断: {claim.get('core_judgment', '')}")

    if audience:
        anchor_parts.append(f"\n### 你的读者\n{audience}")
        anchor_parts.append("在写每一段之前问自己：正在读这段的那个人，看到这里想知道什么？如果这段不能回答他此时心里的问题，重写或删掉。")

    anchor_block = "\n".join(anchor_parts) + "\n\n"

    # Platform-specific tone
    platform = outline.get("platform", "")
    platform_tone = ""
    if platform == "one.weixiaoduo.com":
        platform_tone = (
            "\n### 平台语调\n"
            "one.weixiaoduo.com 面向 WordPress 商业用户和决策者。"
            "写作要有商业视角（成本、效率、ROI），强调解决方案的实际业务价值。"
            "语气专业但不冰冷，可以讲故事但要有事实收尾。\n"
        )

    output_requirements = (
        '- 把主题讲清楚就好，不凑字数。\n'
        '- 直接输出 Markdown 正文。不加"好的""以下是文章"等前缀。\n'
        '- **编造是硬错误**：素材里没有的数据、URL、具体数字、时间点、用户画像、加载速度、价格、地址——这些如果素材没写，你就不写。\n'
        '- 不确定的事不说。少写一段不扣分，编造一段整篇文章废掉。\n'
        '- 不要引用不存在的图表。\n'
    )
    if tier == "TIER_EXTERNAL":
        output_requirements += '- **外部产品文章**：每个事实陈述必须能在参考素材中找到来源。找不到就跳过。\n'

    style_block = render_style_block(category, style_overrides)
    style_prefix = f"\n{style_block}\n" if style_block else "\n"
    return f"""{_genre_rules(category, tier)}{style_prefix}
{samples_block}{anchor_block}## 文章信息
- 标题: {title}
- 关键词: {keyword}
- 核心论点: {outline.get('core_argument', '')}
{platform_tone}
## 段落结构（这是骨架，必须在此基础上充实内容）
{sections_text}

## 参考素材（这是你唯一的信息来源）
{source_note}

## 输出要求
{output_requirements}"""


def _extract_samples(research_note: str) -> list[dict]:
    """Extract writing samples from the research note's 写作范本 section."""
    import re as _re
    samples = []
    # Match patterns like: "1. [B级|technique] claim text"
    pattern = _re.findall(r'\d+\.\s*\[([AB])级\|(\w+)\]\s*(.+?)(?=\n\d+\.\s*\[|$)', research_note, _re.DOTALL)
    for quality, ctype, claim in pattern:
        samples.append({"quality": quality, "type": ctype, "claim": claim.strip()})
    return samples


def _get_api_key() -> str | None:
    return (os.environ.get("AP_DS_API_KEY") or
            os.environ.get("ANTHROPIC_API_KEY") or
            os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _call_with_fallback(system_prompt: str, user_prompt: str,
                        max_tokens: int = 4096) -> dict:
    """Try primary API, then fallback. Returns same dict shape as _call_messages_api."""
    config = load_config()
    ds = config.get("deepseek", {})
    api_key = _get_api_key()
    if not api_key:
        return {"error": "missing_api_key"}

    endpoints = [
        (ds.get("base_url", "https://api.z.ai/api/anthropic"),
         ds.get("model", "glm-5.1")),
        (ds.get("fallback_url", "https://api.deepseek.com/anthropic"),
         ds.get("fallback_model", "deepseek-v4-pro")),
    ]

    for base_url, model in endpoints:
        if not base_url or not model:
            continue
        result = _call_messages_api(base_url, api_key, model,
                                    system_prompt, user_prompt, max_tokens)
        if "error" not in result:
            return result
    return result  # Return last error


def _call_messages_api(base_url: str, api_key: str, model: str,
                       system_prompt: str, user_prompt: str,
                       max_tokens: int = 4096) -> dict:
    max_retries = 3
    backoff = [5, 15, 45]

    for attempt in range(max_retries + 1):
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
            # Don't retry 4xx client errors (except 429)
            if resp.status_code == 429:
                if attempt < max_retries:
                    wait = backoff[attempt]
                    print(f"  [api] Rate limited (429), retrying in {wait}s ({attempt+1}/{max_retries})")
                    time.sleep(wait)
                    continue
            elif 400 <= resp.status_code < 500:
                return {"error": "client_error",
                        "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}

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
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt < max_retries:
                wait = backoff[attempt]
                print(f"  [api] {type(e).__name__}, retrying in {wait}s ({attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            return {"error": "api_unreachable" if isinstance(e, requests.ConnectionError) else "api_timeout",
                    "message": str(e)}
        except requests.RequestException as e:
            return {"error": "request_failed", "message": str(e)}
        except (KeyError, IndexError, TypeError) as e:
            return {"error": "bad_response", "message": str(e)}

    return {"error": "max_retries_exceeded", "message": f"Failed after {max_retries} retries"}


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
    polish_prompt = f"""请对下面这篇关于"{keyword}"的文章做编辑润色。

## 润色重点
- 检查结论是否有明确立场。如果最后是"两者各有千秋"式废话，直接砍掉重写，给出具体场景下的明确选择
- 砍掉没有信息量的句子
- 合并重复段落

## 原文
{article}"""

    return _call_with_fallback(EDITOR_SYSTEM_PROMPT, polish_prompt, 4096)


def write_article(keyword: str, category: str, outline: dict,
                  research_note: str, tier: str = "TIER_INTERNAL",
                  style_overrides: dict | None = None) -> dict:
    samples = _extract_samples(research_note)
    prompt = _build_writer_prompt(keyword, category, outline, research_note, samples, tier=tier,
                                    style_overrides=style_overrides)
    result = _call_with_fallback(WRITER_SYSTEM_PROMPT, prompt,
                                 max_tokens=8192)

    # Polish is DISABLED — GLM-5.1 writes clean enough. Polish was eating 60% of content.

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
                         research_note: str, tier: str = "TIER_INTERNAL",
                         style_overrides: dict | None = None) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "missing_api_key",
                "message": "ANTHROPIC_API_KEY env var not set"}

    samples = _extract_samples(research_note)
    prompt = _build_writer_prompt(keyword, category, outline, research_note, samples, tier=tier,
                                    style_overrides=style_overrides)
    return _call_messages_api("https://api.anthropic.com", api_key,
                              "claude-sonnet-4-6",
                              WRITER_SYSTEM_PROMPT, prompt, 8192)


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
    prompt = _build_revision_prompt(keyword, original_article, suggestions, research_note)
    return _call_with_fallback(REVISION_SYSTEM_PROMPT, prompt, 4096)


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
    source = f"\n\n参考素材:\n{research_note[:2000]}" if research_note else ""

    prompt = f"""请根据以下审稿反馈修改文章。

文章主题: {keyword}

## 审稿反馈
{feedback_text}
{source}

## 原文（请在此基础上修改）
{article}"""

    return _call_with_fallback(HUMAN_FEEDBACK_SYSTEM_PROMPT, prompt, max_tokens=8192)
