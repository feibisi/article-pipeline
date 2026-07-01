# Article Pipeline — 系统定义

> 版本: 0.4.0 | 更新: 2026-07-01 | 维护: elementary VM
> 本文件是本系统的 single source of truth，读这一份即可理解系统是什么、怎么工作。

## 这是什么

Article Pipeline 是一套 AI 原生的中文内容编译系统。它是**编译器**，把知识（cocobook）加意图（选题）加人格（风格坐标）逐级编译为特定格式的高质量内容。

从关键词到 WordPress 发布，全链路自动化，人类只在关键决策点介入。核心区别："级联编译，每层有类型化输出、可检查、可回滚、有门控"，而非"一步到位地生成文章"。

## 设计哲学

**AI 原生优先** — 系统围绕 LLM 的能力边界展开：在 LLM 擅长处（结构化写作、格式遵循、素材整合）放手让它做；在 LLM 不可靠处（事实准确、编造倾向、全局节奏）用结构化约束和门控兜底。

**五层级联编译** — 写作不是一次动作，是逐级细化的编译过程。在写之前，用结构化约束预先替模型做了它做不了的决定（选边、取舍、控制节奏）：

```
SYNTHESIS  (理解)   research 碎片 → 核心判断 + 证据结构 + 矛盾 + 独特性
FRAMEWORK  (方法论) synthesis + genre → 组织骨架 + 论证路径 + 段落职责
STYLE      (风格)   5 维坐标 + genre 预设 → require/allow/avoid 结构化约束
PROSODY    (语感)   style + 范本库 → few-shot 语感范本 + negative constraints
COMPILE    (编译)   以上全部 + 精选素材 → 完整 writer prompt
```

每层独立可测试、可替换、可跳过。层间传递类型化契约（dataclass），不是自由文本。

**双轨约束** — 工程与创作的控制逻辑相反，系统两者都要：

```
工程层（硬约束）保底线 3→7  规则检查 + 自动拦截 + 可验证
  例: AI 句式禁止 / synthesis 门控 / value_density<4 不发 / differentiation 不能空
创作层（软约束）提上限 7→9  advisory 评分 + 范本引导 + 人工复核
  例: 语感范本 / 审美概念激活 / framework 结构可打破 / 坐标 ±0.2 偏离不扣分
```

级联中前 3 层是工程（确定、可回滚），第 4 层是创作（范本引导、允许意外），第 5 层混合。

**Trust Tier** — 事实层约束，作用于 research/synthesis 层（非顶层控制模型）。规定"能不能写"：信息来源边界。INTERNAL 可自由发挥，EXTERNAL 需事实-素材交叉验证。

## 核心假设

1. **LLM 会编造** — 不是偶尔，是必然。所有事实必须有素材支撑，没有素材宁可留空。
2. **LLM 分步做一件事 > 同时做四件事**（待验证假设）— writer 一次同时承担理解、分析、判断、表达四项负载时，会选最省力路径（串碎片、加连接词、通顺但空洞）。拆成级联后每层只做一件事，理应更好。这是级联架构的核心赌注，需 A/B 验证。
3. **LLM 能遵循结构指令** — 给定明确骨架和 require/avoid 约束，LLM 能按要求输出。结构化约束远强于散文指令。
4. **LLM 对风格微调不敏感** — 冷到暖能感知，+0.3 到 +0.6 基本无感。坐标精度为人类编辑服务。
5. **审查可自动化** — 大部分质量问题可用模式匹配 + 语义搜索发现，硬约束自动拦截，软约束 advisory。

## 核心架构

```
┌──────────────────────────────────────────────────────────────┐
│           article-pipeline（单体，级联编译引擎）                  │
│                                                                │
│  research → SYNTHESIS → FRAMEWORK → STYLE → PROSODY → COMPILE  │
│    │           │门控        │门控      (配置)   (范本)     │      │
│    │           ▼           ▼                             ▼      │
│    │      素材不足/     方法论不       token 超限          │      │
│    │      无判断→拦截   匹配→回退      →裁剪素材      write→review │
│    │                                                    →publish │
│  ┌─┴──────────────────────────────────────────────────────┐   │
│  │  genres/（可插拔品类域，21 品类 × 5 文件契约）             │   │
│  │  <genre>/ manifest.yaml framework.yaml style_preset.yaml │   │
│  │           genre_rules.yaml prosody_samples/              │   │
│  │  加新品类 = 放一个目录，不改 Python 代码                    │   │
│  └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────┬─────────────────────────────┘
                                    │ 接入点
                           cocobook 知识库（MCP）
                           synthesis 的理解基础（非搜索引擎）

> creative-core 共享核心库（style/knowledge/llm/quality 抽离）= Phase 4+ 远期规划。
> 当前系统是 article-pipeline 单体，尚未解耦。
> Studio 视觉协作（visual_brief → 配图）= P4 设计意图，当前不实施。
```

## 数据流

```
1. add(keyword, category, platform)              → status=queued
2. research   cocobook 检索 + DDG + 内容农场过滤   → sources dict
3. synthesis  多源对比 → 核心判断/矛盾/独特性       → SynthesisOutput
              [门控: confidence<0.4 → "无差异化空间"，拦截不进入下层]
4. framework  按 genre 选方法论 → 组织骨架          → FrameworkOutput
              [门控: 方法论与素材不匹配 → 回退重选]
5. style      5 维坐标 + genre 预设 → 结构化约束     → StyleOutput（纯配置，不调 LLM）
6. prosody    坐标匹配范本 → few-shot + 负约束       → ProsodyOutput
7. compile    组装全部 + 精选素材 → writer prompt   [门控: token 超限 → 裁剪素材]
8. write      → article    9. review 10 维评分 + 硬门控    10. (人工复核) → publish
```

## 品类体系（21 种）

### 按写作类型分

| 类型 | 品类 | 注入级别 | 典型 Trust Tier |
|------|------|----------|----------------|
| 搜索型 | tutorial, guide, troubleshooting, comparison, beginner, listicle, resource-roundup, tool-review | full/subtle | INTERNAL |
| 相遇型 | opinion, trend, thought-leadership, editorial, case-study, marketing, brand-marketing, soft-article, product-launch | full/subtle | INTERNAL/EXTERNAL |
| 告知型 | announcement, news | none | 视情况 |
| 专题型 | wp-tech, book-knowledge | full | INTERNAL |

### 品类选择决策树

```
写给谁看？
├─ 有明确搜索意图的人 → 搜索型
│   ├─ 想学怎么做 → tutorial / guide / beginner
│   ├─ 遇到问题 → troubleshooting
│   ├─ 想选方案 → comparison / tool-review
│   └─ 想找资源 → listicle / resource-roundup
├─ 没在找你的人 → 相遇型
│   ├─ 给他一个没想过的角度 → opinion / trend / thought-leadership / editorial
│   ├─ 让他觉得你懂行 → brand-marketing
│   ├─ 让他不知不觉被引导 → soft-article
│   ├─ 告诉他产品变了 → product-launch
│   └─ 让他觉得"我也能做到" → case-study
└─ 关注更新的人 → 告知型 (announcement / news)
```

## 系统边界

**做什么**: 21 种品类的中文文章；WordPress 发布（Gutenberg 区块）；research→synthesis→framework→style→prosody→compile→write→review→publish 全流程。

**不做什么**: 小说/剧本/诗歌（需独立管线）；视频脚本（studio VM）；翻译（translate VM）；实时新闻（无法验证时效性事实）。

**边界自知**（明确自身局限，避免产出垃圾）:
- research 素材不足 → 标记"素材不足，需补充"，不强行写
- synthesis 无法形成判断（来源全一致、无矛盾无独特性）→ 标记"选题无差异化空间"
- writer 产出 ai_check < 4.0 → 不走 revise，标记"prompt 约束失效，回溯诊断"

## 质量标准

### 硬门控（工程层，不通过则不发布）

- value_density < 4.0（独占信息比过低，三档规则：< 4.0 → fail/slop；4.0~6.0 → needs_human；>= 6.0 → pass）
- Humanizer 总分 < 30/50
- 编造检查 fabrication_flags > 2
- differentiation 字段为空
- AI 检测模式分 < 门槛

### 加权总分（满分 10，创作层部分为 advisory）

| 维度 | 权重 | 检查内容 |
|------|------|----------|
| value_density | — | 独占信息比（硬门控，>20% 独占信息） |
| humanizer | 0.27 | 5 维人味评分（直接性/节奏/信任度/真实性/精炼度） |
| ai_check | 0.15 | 40+ AI 套话模式检测 |
| fabrication | 0.15 | 伪造 URL/来源/数据 |
| cross_reference | 0.12 | 事实-素材交叉验证（仅 TIER_EXTERNAL） |
| semantic_facts | 0.10 | cocobook 语义验证 |
| format | 0.07 | 结构完整性 |
| word_count | 0.07 | 字数达标 |
| jargon | 0.07 | 管理黑话/圈内术语检测 |

### 信息性检查（advisory，不阻断）

GEO 优化（Frase 5 维）、术语规范（WP 中文术语表）、事实引用追溯、语感合规（软约束）。

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| 语言 | Python 3.11+ | 纯 Python，无框架依赖 |
| LLM | GLM-5.1 (z.ai, 主力) + DeepSeek (备选) + Claude (备选) | 级联中不同层可用不同模型（synthesis 用便宜模型跑多次，write 用强模型） |
| 知识库 | cocobook MCP (huawei-pc:8087) | 全文检索 + 语义搜索；synthesis 的理解基础 |
| 品类域 | genres/ (yaml + txt) | 可插拔，5 文件契约，validate_genres.py 校验 |
| 任务队列 | SQLite | 本地轻量，单 VM 运行 |
| 发布 | WordPress REST API | Gutenberg 区块格式 |
| 审查 UI | review_server.py (localhost:8765) | 内置 Web UI |
