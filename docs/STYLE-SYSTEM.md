# 文风格调系统 — 技术说明书

> 模块: `article_pipeline/style.py` | 设计文档: `docs/ai-context/article-pipeline-style-design.md`

## 概述

文风格调系统用五维连续坐标系替代离散的 if-else 体裁规则，为每篇文章生成可执行的风格指令注入到 LLM 写作 prompt 中。

核心组件：
1. **StyleVector** — 五维坐标数据结构
2. **品类预设表** — 21 种品类的默认坐标值
3. **维度映射规则** — 坐标值 → 自然语言写作指令
4. **注入分层** — none/subtle/full 三级控制风格指令强度
5. **中文审美概念** — 来自经典写作理论的高层指令

## 五维坐标系

每个维度是 [-1.0, +1.0] 的连续谱。坐标值被量化到 4 个区间，每个区间映射一条自然语言写作指令。

| 维度 | 英文 | -1.0 端 | +1.0 端 | 实际控制 |
|------|------|---------|---------|----------|
| 疏密 | density | 短句、留白、一段一意 | 信息密集、段落绵长 | 段落长度与信息节奏 |
| 冷暖 | warmth | 客观、数据驱动、第三人称 | 亲近、有故事感、"我们" | 情感距离与人称选择 |
| 动静 | energy | 平实、陈述句为主 | 冲击力、短句密集、反问 | 句式节奏与修辞强度 |
| 雅俗 | register | 书面语、术语规范 | 口语化、类比、聊天感 | 词汇正式度 |
| 锐钝 | edge | 多角度、留余地 | 判断前置、指出错误 | 立场强度与确定性 |

### 区间映射（以 warmth 为例）

| 坐标区间 | 生成的写作指令 |
|---------|--------------|
| -1.0 ~ -0.5 | 全程第三人称。不出现"你""我们"。用数据和事实说话，不讲故事。 |
| -0.5 ~ +0.0 | 偶尔用"你"但不拉近距离。保持专业距离感。 |
| +0.0 ~ +0.5 | 用"你"和读者对话。可以讲一个简短的场景（不超过两句）引入问题。 |
| +0.5 ~ +1.0 | 可以用"我们"构建共同体验。用场景和故事说明问题。每 2-3 段有一个读者能代入的瞬间。 |

5 维 x 4 区间 = 20 条映射规则（完整列表见 style.py `_DIM_RULES`）。

## 注入分层

与 Trust Tier 正交。Tier 管事实边界（能不能写），注入级别管文风强度（写多好看）。

| 级别 | 行为 | 品类 |
|------|------|------|
| **none** | 不生成风格指令。纯信息传递。 | announcement, news |
| **subtle** | 注入 2 条指令（density + edge）。事实边界内增强可读性。 | resource-roundup, tool-review, product-launch, brand-marketing, soft-article, marketing |
| **full** | 注入全部 5 条维度指令 + 审美概念。作者声音鲜明。 | tutorial, opinion, comparison, guide, troubleshooting, beginner, case-study, listicle, trend, thought-leadership, editorial, wp-tech, book-knowledge |

## 中文审美概念

5 条来自经典写作理论的高层指令。仅 full 级别注入。

| 概念 | 指令 |
|------|------|
| 文气 | 段落间保持呼吸节奏——长段铺陈后接一个判断短句。三段密一段疏。句子长度有意变化，形成内在韵律。 |
| 风骨 | 核心判断句前置。不用"或许""可能""似乎"修饰主要论点。论据支撑判断，判断不因论据妥协。 |
| 留白 | 关键结论写出后不停留，不解释。留给读者思考。段落间有意留空，不用过渡句填满。 |
| 分寸 | 技术描述精确到数字（"TTFB 从 800ms 降到 200ms"），不写"大幅提升"。情感描述点到为止，不煽情。 |
| 意在言外 | 结尾不总结全文。用一个具体画面、一个未解答的问题、或一个假设场景收束。让读者带着思考离开。 |

## 品类预设表

| 品类 | density | warmth | energy | register | edge | injection |
|------|---------|--------|--------|----------|------|-----------|
| tutorial | +0.3 | +0.6 | +0.2 | -0.2 | +0.2 | full |
| opinion | +0.1 | +0.2 | +0.7 | -0.1 | +0.9 | full |
| comparison | +0.4 | +0.0 | +0.2 | -0.3 | +0.5 | full |
| guide | +0.3 | +0.4 | +0.1 | -0.3 | +0.4 | full |
| troubleshooting | +0.2 | +0.1 | +0.3 | -0.2 | +0.7 | full |
| beginner | -0.4 | +0.8 | -0.2 | +0.2 | -0.1 | full |
| case-study | +0.0 | +0.6 | +0.3 | +0.1 | +0.5 | full |
| listicle | -0.2 | +0.5 | +0.3 | -0.1 | +0.4 | full |
| trend | +0.3 | +0.0 | +0.4 | -0.4 | +0.6 | full |
| thought-leadership | +0.2 | +0.1 | +0.6 | -0.3 | +1.0 | full |
| editorial | +0.1 | +0.3 | +0.7 | -0.1 | +0.9 | full |
| resource-roundup | +0.2 | +0.4 | +0.1 | -0.2 | +0.3 | subtle |
| tool-review | +0.1 | -0.1 | +0.2 | -0.3 | +0.5 | subtle |
| product-launch | -0.2 | +0.4 | +0.4 | -0.1 | +0.6 | subtle |
| brand-marketing | +0.1 | +0.5 | +0.5 | +0.0 | +0.6 | subtle |
| soft-article | +0.0 | +0.5 | +0.2 | -0.1 | +0.3 | subtle |
| marketing | -0.1 | +0.4 | +0.5 | +0.0 | +0.5 | subtle |
| announcement | -0.5 | -0.3 | +0.0 | -0.5 | +0.4 | none |
| news | -0.4 | -0.4 | +0.1 | -0.5 | +0.3 | none |
| wp-tech | +0.3 | +0.3 | +0.2 | -0.2 | +0.3 | full |
| book-knowledge | +0.0 | +0.6 | -0.1 | +0.1 | +0.2 | full |

## 与 Writer Prompt 的集成

`render_style_block(category, overrides)` 生成完整风格指令块，在 writer.py 中注入到 LLM prompt：

```
┌─────────────────────┐
│ Genre Rules         │  ← _genre_rules(): 体裁硬规则（当前优先级最高）
├─────────────────────┤
│ Style Block         │  ← render_style_block(): 5 维指令 + 审美概念
├─────────────────────┤
│ Samples + Anchor    │  ← 写作范本 + claim/audience/hook
├─────────────────────┤
│ 段落结构 + 素材     │  ← outline + research_note
├─────────────────────┤
│ 输出要求           │  ← 编造红线 + 格式要求
└─────────────────────┘
```

### 覆盖机制

单篇文章可通过 `style_overrides` dict 覆盖任意维度：

```python
# 例：让一篇 tutorial 写得更犀利
write_article(keyword, category="tutorial",
              style_overrides={"edge": 0.7})
```

### 退出机制

预设表中 `active: bool` 字段可关闭特定品类的风格系统：

```python
# 如果某品类效果不好，设 active=False 回退到纯 genre_rules
```

## 与 Review 的对接

review 结果中包含 `style_coordinates` 和 `style_humanizer_map`，展示文章目标风格坐标和 humanizer 维度的参考映射：

```json
{
  "style_coordinates": {"density": 0.3, "warmth": 0.6, ...},
  "style_humanizer_map": {
    "density": {"humanizer_dim": "节奏", "style_value": 0.3},
    "warmth": {"humanizer_dim": "信任度", "style_value": 0.6},
    ...
  }
}
```

注意：此映射为参考性质，非严格因果。详见审计报告中的说明。

## API 速查

```python
from article_pipeline.style import (
    StyleVector, Injection,
    get_preset,          # category → StyleVector
    get_preset_dict,     # category → dict
    render_temperament,  # StyleVector → list[str] (5 条指令)
    render_injection,    # StyleVector → str (带标题的指令块)
    render_aesthetic_concepts,  # → str (审美概念块)
    render_style_block,  # category + overrides → str (完整风格块)
    STYLE_TO_HUMANIZER,  # dict: style dim → humanizer dim
)
```

## 已知局限与改进方向

1. **LLM 对连续值不敏感** — +0.3 和 +0.5 的区别在 LLM 输出中几乎不可观测。坐标精度的真正价值是给人类编辑提供可调参界面。
2. **审美概念未按品类筛选** — 全部 5 条一次性注入，某些概念与特定品类的 genre_rules 冲突（如 beginner 需要详细解释，而"留白"要求不解释）。
3. **缺少风格遵循度评分** — 系统能告诉你"目标是 warmth=+0.6"，但无法评估文章实际达到了什么 warmth 水平。
4. **subtle 级别维度选取** — 设计意图取 density + edge，当前实现取前 2 条（density + warmth）。
