# Article Pipeline — 风格系统改造与架构重构执行方案

> 2026-07-01 | 可执行的完整方案，不是愿景文档。
> 前置文档：ARCHITECTURE-GAPS.md（诊断）、EVOLUTION-PLAN.md（路径规划）
> 本文档定位: Phase 级架构规划（设计方案 + 验收标准）。不含具体时间排期。
> 执行级任务清单见 ROADMAP.md；方向级发展规划见 EVOLUTION-PLAN.md。

---

## 改造后的系统定义

### 一句话

**基于结构化知识理解的中文内容编译系统。**

不是"AI 写作工具"，不是"内容生产管线"，不是"自动化发文机器"。

是**编译器**，把知识（cocobook）加意图（选题）加人格（风格坐标）编译为特定格式的高质量内容。

### 为什么是"编译器"而非"生成器"

| | 生成器（当前） | 编译器（目标） |
|---|---|---|
| 输入 | keyword + category | 结构化理解 + 方法论 + 风格配置 |
| 过程 | 一步到位（素材→文章） | 级联编译（5 层逐级细化） |
| 中间产物 | 无（黑盒） | 每层有类型化输出，可检查可回滚 |
| 质量保障 | 事后检测 | 每层有门控，知道自己什么时候不行 |
| 扩展方式 | 加 if-else | 放一个新目录（可插拔知识域） |
| 风格控制 | 散文指令（LLM 自由解读） | 结构化约束（purpose/require/allow/avoid，机器可检查） |

### 核心架构（改造后）

```
                    ┌─────────────────────────────────┐
                    │     creative-core（共享核心库）     │
                    │  style / knowledge / llm / quality │
                    └──────────────┬──────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         │                         │                         │
  article-pipeline          screenplay-pipeline        video-script-pipeline
  (文章编译器)               (剧本编译器)              (短视频脚本编译器)
         │                         │                         │
    ┌────┴────┐               ┌────┴────┐              ┌────┴────┐
    │ genres/ │               │ genres/ │              │ genres/ │
    │  5-file │               │  5-file │              │  5-file │
    │ contract│               │ contract│              │ contract│
    └─────────┘               └─────────┘              └─────────┘
```

### 与 Studio 的协作接口

```
elementary（文本编译器）                    studio（视觉编译器）
  article-pipeline                           prompts pipeline
  screenplay-pipeline                        image-gen pipeline
  video-script-pipeline ───契约──→           video pipeline
                                             brand pipeline

共享层:
  - creative-core/style/ ←→ shared/brand-config/（风格坐标 ↔ 品牌 VI）
  - creative-core/knowledge/ ←→ cocobook MCP（知识服务）
  - NATS 即时通信（任务调度、素材请求）
```

协作流程示例（品牌内容套件）：
1. elementary 编译文章（blog post）→ 输出结构化 JSON（标题/摘要/关键视觉描述）
2. NATS 通知 studio：`{type: "content_ready", format: "blog_post", visual_brief: {...}}`
3. studio 接收 visual_brief → compose pipeline 生成配图 → 返回素材路径
4. elementary 组装最终产出物（文章 + 配图）→ 发布

---

## 级联编译架构（5 层）

### 层级定义

```
Layer 1: SYNTHESIS（理解）
  输入: research 原始素材
  输出: SynthesisOutput（核心判断 + 证据结构 + 矛盾 + 独特性）
  门控: 无法形成判断 → 标记"选题无差异化空间"，不进入下层

Layer 2: FRAMEWORK（方法论）
  输入: SynthesisOutput + genre manifest
  输出: FrameworkOutput（组织骨架 + 论证路径 + 段落职责分配）
  门控: 方法论与素材不匹配 → 回退重选框架

Layer 3: STYLE（风格编译）
  输入: style 坐标 + genre style_preset
  输出: StyleOutput（结构化约束: require/allow/avoid + 渲染后的指令文本）
  门控: 无（纯配置层，不调 LLM）

Layer 4: PROSODY（语感注入）
  输入: StyleOutput + genre prosody_samples/
  输出: ProsodyOutput（few-shot 范本 + negative constraints）
  门控: 无合适范本 → 降级为纯 negative constraints

Layer 5: COMPILE（最终编译）
  输入: FrameworkOutput + StyleOutput + ProsodyOutput + validated material（精选素材）
  输出: 完整 writer prompt
  门控: prompt token 超限 → 按优先级裁剪（validated material 最先被裁）
  说明: validated material 是 compile 的输入之一，不是独立层。"素材最后注入"指的是在 compile 组装时素材排在 prompt 最后位置（LLM 注意力分配考虑）。
```

### 类型化契约

```python
# Layer 1 → Layer 2
@dataclass
class SynthesisOutput:
    core_judgment: str          # 一句话：这篇文章要传递什么理解
    evidence_for: list[dict]    # [{source, claim, strength}]
    evidence_against: list[dict]
    conflicts: list[dict]       # [{source_a, source_b, claim_a, claim_b, resolution}]
    unique_claims: list[str]    # DDG 前 10 结果中找不到的 claim
    differentiation: str        # 比搜索第一页多给读者什么（生成于 synthesis，门控在 outline 阶段验证）
    confidence: float           # 0-1，synthesis 对自己判断的信心

# Layer 2 → Layer 5
@dataclass
class FrameworkOutput:
    method: str                 # 使用的方法论名（e.g. "steel_man_refutation"）
    structure: list[dict]       # [{role, h2_title, purpose, evidence_ids, word_budget}]
    takeaway: str               # 一句话卖点
    reader_entry_state: str     # 读者进来时认为什么（要被翻转或确认的）
    reader_exit_state: str      # 读者出去时应该理解什么
    visual_anchors: list[dict] | None = None  # [{section_role, concept, visual_type, screenshot_target?, diagram_spec?}]
    # visual_anchors 设计意图: Phase 5 素材集成时激活，当前阶段为 None

# Layer 3 → Layer 5
@dataclass
class StyleOutput:
    vector: StyleVector         # 5 维坐标值
    constraints: dict           # {require: [...], allow: [...], avoid: [...]}
    rendered_instructions: str  # 人类可读的风格指令文本（给 LLM 参考）
    aesthetic_concepts: list[str]  # 适用的审美概念子集

# Layer 4 → Layer 5
# Layer 4 → Layer 5（创作层：范本引导，允许偏离，不做强制合规检查）
@dataclass
class ProsodyOutput:
    samples: list[str]          # 2-3 个语感范本段落
    sample_type: str            # 范本类型（short_push / flowing / staccato / ...）
    negative_constraints: str   # 硬性禁止列表
    rhythm_hint: str            # 一句话节奏提示（e.g. "短句密集推进，长句仅在总结时出现"）
```

---

## 可插拔品类域（Genre Domain）

### 目录结构

```
article_pipeline/genres/
├── _schema.yaml              # 域文件契约定义（验证用）
├── tutorial/
│   ├── manifest.yaml         # 元信息 + 触发关键词 + 适用场景
│   ├── framework.yaml        # 方法论定义（认知脚手架法）
│   ├── style_preset.yaml     # 风格预设 + 结构化约束(require/allow/avoid)
│   ├── genre_rules.yaml      # 硬性写作规则（从 writer.py _genre_rules 迁出）
│   └── prosody_samples/      # 语感范本（2-5 个 .txt 文件）
│       ├── short_push.txt    # 短句推进型
│       └── scaffold.txt      # 层层递进型
├── comparison/
│   ├── manifest.yaml
│   ├── framework.yaml        # 维度统一法
│   ├── style_preset.yaml
│   ├── genre_rules.yaml
│   └── prosody_samples/
├── opinion/
│   ├── manifest.yaml
│   ├── framework.yaml        # Steel-man 反驳法
│   ...
├── troubleshooting/
├── case-study/
├── guide/
├── editorial/
├── beginner/
├── trend/
├── news/
├── announcement/
├── product-launch/
├── brand-marketing/
├── soft-article/
├── marketing/
├── listicle/
├── resource-roundup/
├── tool-review/
├── book-knowledge/
├── wp-tech/
└── thought-leadership/
```

### manifest.yaml 示例（tutorial）

```yaml
domain: tutorial
name: 教程
description: "手把手教读者完成一个具体任务"
version: 1.0.0
status: validated

trigger_keywords:
  - 教程
  - 如何
  - 怎么
  - 入门
  - 步骤
  - 操作指南

trust_tier: INTERNAL
injection_level: full

preferred_framework: cognitive_scaffold
fallback_framework: step_by_step

prosody_type: short_push
aesthetic_concepts: ["分寸", "文气"]

quality_thresholds:
  min_value_density: 5.0
  min_verifiable_operations: 0.3   # 可验证操作段落占比
  max_ai_check_violations: 3

compatible_platforms:
  - wptea
  - juejin
  - wpcommunity
  - linuxjoy

word_count:
  min: 1200
  max: 3000
  target: 1800
```

### style_preset.yaml 示例（tutorial）

```yaml
vector:
  density: 0.0       # 中性（不过度压缩也不啰嗦）
  warmth: 0.4        # 偏暖（引导而非命令）
  energy: 0.3        # 中等偏快（推进但不急）
  register: 0.2      # 略口语（亲切但不随意）
  edge: -0.2         # 略钝（教程不需要犀利判断）

constraints:
  purpose: "让新手建立心理模型后能独立完成操作"
  require:
    - 开头展示终态（做完后得到什么）
    - 每个步骤包含验证点（怎么确认这步做对了）
    - 使用具体命令/代码/截图而非泛泛描述
    - 新概念首次出现时用一句话解释
  allow:
    - 类比说明抽象概念
    - 假设场景铺设动机
    - 口语化过渡句
    - 作者经验插入（"我第一次也踩了这个坑"）
  avoid:
    - 抽象理论先行（先讲原理再操作）
    - 无验证的步骤列表（没有"怎么确认做对了"）
    - 上来就操作无全貌（读者不知道目标）
    - "各种方法请根据需要选择"（应给出具体建议）
    - 信息密度过低的铺垫段落

model_calibration:
  glm: {edge: +0.1, energy: +0.1}      # GLM 默认偏保守，补一点
  claude: {warmth: -0.1, register: -0.1} # Claude 默认偏亲切口语，收一点
```

### framework.yaml 示例（tutorial — 认知脚手架法）

```yaml
name: cognitive_scaffold
display_name: 认知脚手架法
description: "先给全貌建心理模型，再拆步骤，每步说清为什么在这里"

principle: |
  人在没有全貌时学步骤 = 纯记忆负担（工作记忆 7±2 限制）。
  先给一个可视化的心理模型（"整体长什么样"），再填充细节。
  每步不只是"做什么"，还有"为什么这一步在这里"和"怎么验证做对了"。

structure:
  - role: opening
    purpose: "展示终态 + 建立动机"
    pattern: "做完后你会得到 X。需要 Y 分钟。前提是 Z。"
    word_budget: 100-200
    
  - role: mental_model
    purpose: "给出全貌心理模型"
    pattern: "整体分 N 部分，它们的关系是...（可用图/列表/类比）"
    word_budget: 200-400
    
  - role: steps
    purpose: "逐步骤执行"
    pattern: "每步：做什么 → 为什么 → 验证点（怎么确认做对了）"
    word_budget: 800-1500
    repeatable: true
    
  - role: detours
    purpose: "常见岔路和错误处理"
    pattern: "如果你看到 X 错误，说明 Y，解决方法是 Z"
    word_budget: 200-400
    optional: true
    
  - role: next_steps
    purpose: "指向进阶资源"
    pattern: "现在你能做 A 了。下一步可以学 B（链接）。"
    word_budget: 100-150

anti_patterns:
  - name: "上来就操作"
    description: "跳过心理模型直接第一步打开终端"
    fix: "先告诉读者要去哪里、整体分几步"
  - name: "步骤无验证"
    description: "只说做什么不说怎么确认对了"
    fix: "每步加'验证：运行 X，如果看到 Y 说明成功'"
  - name: "列步骤不解释"
    description: "1. 运行 A  2. 运行 B  3. 运行 C（读者不知道为什么）"
    fix: "每步加一句'这一步的目的是...'"

source_books:
  - "《写作法宝》— William Zinsser（简洁与清晰）"
  - "《如何阅读一本书》— Mortimer Adler（理解层次模型）"
  - "认知负荷理论 — John Sweller"
```

---

## 实施执行表

### Phase 0: 基础设施（第 1-2 周）

| 任务 | 产出物 | 验证标准 | 依赖 |
|------|--------|----------|------|
| 创建 genres/ 目录结构 | 21 个品类目录 + _schema.yaml | `validate_genres.py` 全通过 | 无 |
| 迁移 _genre_rules 到 genre_rules.yaml | 19 个品类的规则文件 | writer.py 读 yaml 等价于读硬编码 | 无 |
| 迁移 _PRESETS 到 style_preset.yaml | 21 个品类的预设文件 | style.py 读 yaml 等价于读硬编码 | 无 |
| 编写 5 核心品类的 framework.yaml | tutorial/comparison/opinion/troubleshooting/case-study | 人工审阅方法论是否合理 | 无 |
| 建立阶段契约 dataclass | 4 个 Output dataclass | pytest 类型测试通过 | 无 |
| anti-ai-patterns 分支合入 main | writer.py negative constraints + ai_detection 分模型权重 | 85 测试全过 | 子代理已完成 |

### Phase 1: Synthesis 层（第 3-4 周）

| 任务 | 产出物 | 验证标准 | 依赖 |
|------|--------|----------|------|
| 新建 synthesis.py | SynthesisOutput 生成函数 | 对 3 个已知选题输出合理判断 | Phase 0 契约 |
| synthesis prompt 设计 | 结构化分析 prompt（禁止写散文） | 输出可被 dataclass 解析 | 无 |
| 集成到 pipeline.py | research → synthesis → outline 流程 | pipeline run 不报错 | synthesis.py |
| synthesis 质量门控 | confidence < 0.4 → 不进入 outline | 素材不足的选题被正确拦截 | synthesis.py |
| value_density 评分（T-013） | review/value_density.py | 区分已发布文章(>6) vs slop(<4) | 无（独立） |
| differentiation 字段（T-014） | outline prompt 改造 | outline 输出包含具体 differentiation | synthesis.py |

**门控类别说明**: 
- 纯规则硬门控（确定性）: 句式禁令、字段非空、字数达标
- LLM 辅助硬门控（有误判可能）: 独占信息比、反直觉度 — 这类检测依赖 DDG 搜索结果和 LLM claim 提取，有不稳定性。实施时需加 confidence 阈值，低置信度时降级为 advisory 而非硬拦截。
- Advisory（参考）: 正向质量信号、GEO 评分

### Phase 2: Framework 层（第 5-6 周）

| 任务 | 产出物 | 验证标准 | 依赖 |
|------|--------|----------|------|
| framework 加载器 | 读 framework.yaml → FrameworkOutput | 5 品类正确加载 | Phase 0 yaml 文件 |
| outline prompt 改造 | 基于 FrameworkOutput 生成 outline（非模板） | outline 体现方法论结构 | framework 加载器 |
| outline 质量评估 | 对比：模板版 vs 方法论版（人工评） | 方法论版明显更有组织逻辑 | Phase 1 synthesis |
| 剩余 16 品类 framework.yaml | 从 cocobook writing-craft 提取 | 人工审阅 | 5 核心品类验证通过 |

### Phase 3: Prosody 层（第 7-8 周）

| 任务 | 产出物 | 验证标准 | 依赖 |
|------|--------|----------|------|
| 范本库建设 | 从 chinese-writing topic 分类提取 30+ 段落 | 每种语感类型 5+ 范本 | 无 |
| 范本分类器 | 按 energy/register 坐标选匹配范本 | 高 energy 选短句推进型，低 energy 选从容铺陈型 | 范本库 |
| prosody 注入 writer prompt | few-shot 段落 + rhythm_hint | 对比：有范本 vs 无范本的产出差异 | 范本分类器 |
| style_compliance 评分（T-006） | 验证产出是否遵循了语感指令 | 5 维度各有量化检查 | Phase 2 完成 |

### Phase 4: 解耦 + 验证（月 3）

> 注意: creative-core 解耦在只有一个消费者（article-pipeline）时不做。等第二条管线真正开工、明确了共享需求后再提取。过早解耦几乎必然产生错误的抽象边界。Phase 4 的前置条件是：第二条管线的需求已明确。

| 任务 | 产出物 | 验证标准 | 依赖 |
|------|--------|----------|------|
| 提取 creative-core 库 | style/ knowledge/ llm/ quality/ 四模块 | article-pipeline 依赖 creative-core 后全测试通过 | Phase 1-3 |
| Studio 协作契约 | elementary↔studio JSON 契约定义 | validate_contracts.py 校验通过 | creative-core |
| 跑 20 篇文章端到端 | 20 篇通过 value_density > 6.0 的文章 | 人工审核通过率 > 70% | 全部 Phase |
| A/B 验证 | 改造前 vs 改造后同选题对比（10 组） | 改造后明显更好的占比 > 70% | 20 篇产出 |

### Phase 5: 多管线扩展（月 4+）

| 任务 | 产出物 | 验证标准 | 依赖 |
|------|--------|----------|------|
| 第二条管线原型 | video-script-pipeline 或 Linux/DevOps 文章 | 基于 creative-core 搭建，不改核心库 | Phase 4 |
| Studio 联动验证 | 一次完整的"文章 + 配图"联合产出 | NATS 契约跑通 | Phase 4 |

---

## 系统改造后的重新定义

### 改造前（当前系统）

> AI 内容生成工具：keyword → 搜素材 → 套模板 → 写文章 → 检测 AI 味 → 发布

问题：生产的是高级 slop，通顺但空洞，因为系统没有理解任何东西。

### 改造后（目标系统）

> **知识编译器**：知识库中的结构化理解 × 创作者人格 × 格式方法论 → 有独特判断的内容

核心区别：

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| 知识作用 | 搜索引擎（搜到什么用什么） | 理解基础（从碎片形成判断） |
| 写作驱动 | keyword 驱动 | judgment 驱动（先有判断再写） |
| 质量定义 | "不像 AI" | "有别人给不了的东西" |
| 风格控制 | 散文指令（LLM 自由解读） | 结构化约束（机器可检查） |
| 管线结构 | 一步到位（research→write） | 级联编译（5 层，每层有门控） |
| 扩展方式 | 改代码 | 放目录（可插拔品类域） |
| 边界自知 | 没有（硬着头皮出垃圾） | 有（素材不足/无判断/prompt 失效 → 自动停止） |

### 系统名重新定义

**article-pipeline** 这个名字不再准确。改造后它是：

**Inkwell** — 知识编译引擎

```
Inkwell = cocobook（知识） + creative-core（人格/能力） + genre pipelines（格式引擎）
```

命名逻辑：inkwell（墨水池）是写作的物理源头。所有格式的内容都从同一个知识池中汲取，但通过不同的笔（管线）写出不同形态。

（或者保持 article-pipeline 作为第一条格式管线的名字，Inkwell 作为整体系统名。你定。）

---

## 与 Studio 的协作契约（草案）

> 状态: 设计意图文档。当前不实施，Phase 4+ 对接时再固化为实施规格。两边都没有实现代码前，此契约仅供参考方向，预期对接时会根据实际需求调整。

### 设计原则：AI 原生 + 可复用 + 双向感知

跨 VM 协作的核心问题：**资源消耗透明化**。elementary 请求生图用的是 Studio 的 API 额度和计算资源，双方必须知道发生了什么。

```
原则 1: 请求方声明意图和预算，执行方决定如何完成
原则 2: 每次资源消耗都有审计记录（谁触发、用了什么模型、花了多少）
原则 3: 契约可被其他 VM 复用（modiqi 也可能需要配图）
原则 4: 异步为主，不阻塞文章产出流程
```

### elementary → studio 契约

```yaml
contract: elementary-to-studio
version: "2.0"
trigger: visual_brief_ready
format: JSON via NATS
channel: vm.studio.visual-request

fields:
  type: "visual_brief"
  request_id: string              # 唯一请求 ID（追踪+去重）
  requester: string               # "elementary"（谁发的）
  article_id: string
  brand: string                   # wenpai / modiqi / feibisi
  title: string
  summary: string                 # 50 字以内摘要

  # 素材需求清单（一次请求可含多张图）
  assets_requested:
    - role: string                # hero_image / inline_figure / social_card / og_image
      visual_type: string         # "scene" / "diagram" / "brand" / "data_chart"
      concept: string             # 核心视觉意象描述（给 prompts compose 的输入）
      mood: string                # 从 style 坐标推导的氛围词
      dimensions:
        ratio: string             # "16:9" / "1:1" / "1200x630"
      constraints:
        require: list[string]     # 必须包含的视觉元素
        avoid: list[string]       # 不应出现的视觉元素
      reference_domain: string    # prompts 系统的域提示（如 "xiaohei-scenes"）

  # 资源感知字段
  budget:
    priority: int                 # 1=普通 2=重要 3=紧急
    max_cost_hint: string         # "low"(免费模型优先) / "medium" / "high"(最佳效果)
    deadline: string              # ISO8601，超时则标记 timeout（null=不急）
  
  # 上下文（Studio 可用来做更好的图）
  context:
    genre: string                 # 文章品类
    style_vector: dict            # 5 维坐标（供 mood 推导验证）
    target_platform: string       # 发布平台（决定尺寸/风格）
```

### studio → elementary 契约

```yaml
contract: studio-to-elementary
version: "2.0"
trigger: asset_ready OR asset_failed
format: JSON via NATS
channel: vm.elementary.visual-response

fields:
  type: "asset_delivered" | "asset_failed" | "asset_progress"
  request_id: string              # 对应请求 ID
  
  # 交付内容
  assets:
    - role: string                # hero_image / inline_figure / social_card
      path: string                # NAS 路径（/mnt/shared-context/assets/...）
      dimensions: {width: int, height: int}
      format: string              # webp / png / svg
      quality_score: float        # prompts quality_gate 分数
      model_used: string          # "lovart/xxx" / "gpt-image-2" / "gemini-3.1"
  
  # 资源审计
  usage:
    model: string                 # 使用的模型
    api_calls: int                # API 调用次数（含重试）
    estimated_cost: string        # "~$0.04" 或 "free"(本地模型)
    generation_time_ms: int       # 生成耗时
  
  status: "ready" | "needs_revision" | "failed" | "timeout"
  failure_reason: string | null   # 失败原因（status != ready 时）
  notes: string | null            # 可选备注
```

### 审计与感知机制

```yaml
# Studio 侧：每次为外部请求生图，追加到审计日志
# ~/shared/audit/visual-requests.jsonl
{
  "request_id": "elem-art-20260701-001",
  "requester": "elementary",
  "time": "2026-07-01T14:30:00+08:00",
  "model": "lovart/anon-bob",
  "api_calls": 2,
  "estimated_cost": "$0.08",
  "quality_score": 0.78,
  "status": "delivered"
}

# elementary 侧：每次收到交付，追加到本地审计
# ~/Projects/article-pipeline/logs/visual-assets.jsonl
{
  "article_id": "wp-object-cache-tutorial",
  "request_id": "elem-art-20260701-001",
  "assets_received": 2,
  "total_cost": "$0.12",
  "time": "2026-07-01T14:32:00+08:00"
}
```

### 与 Studio shared/interfaces/ 的对接

Studio 已有 `~/shared/interfaces/contracts.md` 定义了 prompts→image-gen 的内部接口。我们的 visual_brief 应该映射到 Studio 已有的输入格式：

```
elementary visual_brief
  → Studio 接收后转换为 prompts compose 输入
  → prompts 编译出 {prompt, negative, dimensions, analysis, quality_gate}
  → image-gen 调度生图
  → 回传资产 + 审计记录
```

elementary 不需要关心 Studio 内部如何路由模型，只声明意图、品质要求和预算提示。Studio 自主决定用哪个后端。

### xiaohei-scenes 集成路径

详见 ROADMAP T-018。执行者为 Studio，elementary 通过 NATS 发 task-request 触发。

---

## 验收标准（改造完成的定义）

改造完成 = 以下全部满足：

1. **级联编译跑通**: keyword 输入 → 5 层各产出类型化中间产物 → 最终文章
2. **品类可插拔**: 新增一个品类 = 放一个目录 + 5 个 yaml/txt 文件，不改 Python 代码
3. **synthesis 有效**: 同一选题，有 synthesis vs 无 synthesis 的文章人工对比，有 synthesis 明显更有深度
4. **framework 有效**: outline 体现方法论逻辑（不是格式模板填充）
5. **边界自知**: 素材不足的选题被自动拦截，不出垃圾
6. **value_density > 6.0**: 产出文章的独占信息比 > 20%
7. **creative-core 解耦**: article-pipeline 依赖 creative-core 但不硬编码在内
8. **Studio 契约跑通**: 至少一次"文章 + 配图"联合产出通过 NATS 完成
9. **可消融 A/B 验证**: 改造前后对比 + 单层贡献度量化
   - **对照组设计**: 每层独立开关，测试 8 种配置
     ```python
     ABLATION_CONFIG = {
         "synthesis": True,    # Layer 1 开关
         "framework": True,    # Layer 2 开关
         "style": True,        # Layer 3 开关
         "prosody": True,      # Layer 4 开关
     }
     # 对照组矩阵
     # - 0001: 只有 prosody
     # - 0010: 只有 style
     # - 0100: 只有 framework
     # - 1000: 只有 synthesis
     # - 1111: 全部开启（完整系统）
     # - 0000: 全部关闭（旧模式 baseline）
     ```
   - **验收标准**:
     - 每层独立贡献度可量化（value_density 提升幅度）
     - 完整系统(1111) vs 单层系统(0001/0010/0100/1000)对比数据
     - 单层开关对质量的影响曲线（可视化）
     - 改造后(1111) vs 旧模式(0000)胜出 >= 7/10
10. **20 篇端到端**: 至少 20 篇文章从选题到发布走完全流程，人工审核通过率 > 70%

---

## 不做清单

以下是明确不做的事（防止再次过度工程化）：

- 不做通用 NLI 矛盾检测模型（用 LLM prompt 即可）
- 不做语感独立建模（Phase 3 只做范本驱动，不建新坐标轴）
- 不做自动 A/B 验证系统（人工对比 10 组够了）
- 不做 review_server UI 大改（现有够用）
- 不建独立的 creative-core 仓库（先作为 article-pipeline 的子目录，验证后再分）
- 不等所有 Phase 完成才产出文章（Phase 1 完成后就开始跑文章）
- 不为未来的剧本/小说管线预建任何代码（只预留接口设计）

---

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| synthesis LLM 调用产出不稳定 | 高 | 中间产物质量不可控 | 强制结构化输出 + 重试 + confidence 阈值 |
| framework.yaml 覆盖不够（21 品类工作量大） | 中 | 部分品类退化到旧模式 | 先做 5 核心品类，其余保持旧逻辑直到手动迁移 |
| 级联编译延迟增加（多了 2 次 LLM 调用） | 高 | 单篇耗时从 2 分钟涨到 5 分钟 | synthesis 用小模型(GLM)；接受延迟（质量 > 速度） |
| cocobook 素材对非 WP 领域覆盖不足 | 中 | 扩展新领域时 synthesis 无法形成判断 | 扩展前先评估 cocobook 覆盖度，不足则先补素材 |
| 改造期间 0 产出（重蹈覆辙） | 高 | 又 N 个月没发文章 | Phase 1 完成后强制每周跑 2 篇，改造与产出并行 |

---

## 从 Studio 借鉴的具体实现细节

### 1. validate_genres.py（品类域验证器）

类似 Studio 的 validate_contracts.py，验证所有品类目录符合 _schema.yaml 契约：

```python
# 检查项
- manifest.yaml 存在且字段完整
- framework.yaml 中 structure 每项有 role + purpose
- style_preset.yaml 中 vector 5 维度值在 [-1, 1] 范围
- genre_rules.yaml 非空
- prosody_samples/ 至少 1 个 .txt 文件
- constraints 有 require + avoid（allow 可选）
```

### 2. 素材密度评估（对标 Studio concept_density）

Studio 发现：概念密度低于阈值时，文字驱动失效，需要参考图锚定。

我们的等价物：cocobook 素材密度低于阈值时，synthesis 无法形成判断，应该：
- 标记选题为"素材不足"
- 触发素材补充流程（搜更多、问 VM peer、或放弃选题）
- 不硬着头皮写空洞文章

```python
def assess_material_density(sources: dict) -> float:
    """
    评估素材是否足够支撑有深度的文章。
    返回 0-1，低于 0.4 建议不写。
    """
    scores = []
    # cocobook 标注数量 >= 3 来源
    scores.append(min(len(sources.get("annotations", [])) / 3, 1.0))
    # 有矛盾观点（说明有深度可挖）
    scores.append(1.0 if has_conflicts(sources) else 0.3)
    # web 文章全文抓取 >= 3 篇
    scores.append(min(len(sources.get("web_articles", [])) / 3, 1.0))
    # topic 索引命中 >= 5 段
    scores.append(min(len(sources.get("topic_paragraphs", [])) / 5, 1.0))
    return sum(scores) / len(scores)
```

### 3. 术语激活效应（对标 Studio 约束压缩理论）

Studio 验证了：书源术语 >> AI 推测术语。生成的图像更写实、更符合物理规律。

写作管线等价：
- cocobook 标注中的 claim（书源） >> LLM 自己编的观点（推测）
- 方法论框架中的术语（"认知脚手架"、"steel-man"）会激活 LLM 训练数据中的学术/专业区域
- framework.yaml 中使用精确方法论术语，比散文描述（"写清楚一点"）更能压缩 LLM 输出空间

### 4. 闭环反馈（对标 Studio A/B 验证 + promote）

Studio: vote → sync → promote → compose（术语验证后提升为主动用词）

我们需要建立等价闭环：

```
publish → 效果数据（阅读量/停留时间/评论）
  → 关联到 synthesis 的 core_judgment 和 framework method
  → 哪些 judgment 类型读者反应好？哪些 framework 效果好？
  → 调整 genre manifest 中的 preferred_framework
  → 下一批文章优先使用验证过的方法论
```

Phase 4 才做（需要先有发布数据），但架构上现在就要预留 feedback 字段。

---

## 本文档维护

- Phase 完成后更新对应验收状态
- 每周五检查：本周是否有文章产出（防止重蹈 0 产出覆辙）
- 月底复审：排期是否需要调整
- 改造完成后归档，SYSTEM-DEFINITION.md 更新为最终版
