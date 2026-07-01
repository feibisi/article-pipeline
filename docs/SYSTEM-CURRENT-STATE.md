# Article Pipeline 当前系统状态定义

> 本文档定义 article-pipeline 0.3.0 当前实现状态，与 OVERHAUL-PLAN.md 核对。
>
> 生成时间：2026-07-02

---

## 系统定义

**article-pipeline** 是一个级联编译型知识文章生产引擎。

### 核心理念

```
知识编译器 = cocobook（知识基础）+ creative-core（人格能力）+ genre pipelines（格式引擎）
```

- **改造前**：keyword → 搜素材 → 套模板 → 写文章 → 检测 AI 味 → 发布（产生高级 slop）
- **改造后**：research → SYNTHESIS → FRAMEWORK → STYLE → PROSODY → COMPILE → write → review → publish

### 架构

```
┌──────────────────────────────────────────────────────────────┐
│           article-pipeline（单体，级联编译引擎）                  │
│                                                                │
│  research → SYNTHESIS → FRAMEWORK → STYLE → PROSODY → COMPILE  │
│    │           │门控        │无门控     (范本)     │token门控    │
│    │           ▼           ▼                             ▼      │
│    │      素材不足/     方法论      范本缺失        token超限    │
│    │      无判断→拦截   不匹配→回退   →使用默认     →裁剪素材    │
│    │                                                    write  │
│  ┌─┴──────────────────────────────────────────────────────┐   │
│  │  genres/（可插拔品类域，21 品类 × 5 文件契约）             │   │
│  │  <genre>/ manifest.yaml framework.yaml style_preset.yaml │   │
│  │           genre_rules.yaml prosody_samples/              │   │
│  └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────┬─────────────────────────────┘
                                    │
                           cocobook MCP (知识库)
```

### 五层级联编译

| 层 | 输入 | 输出 | 门控 | 依赖 |
|----|------|------|------|------|
| **SYNTHESIS** | research 原始素材 | SynthesisOutput（核心判断/证据/矛盾/独特性/信心） | confidence < 0.4 → 拦截 | cocobook MCP + DDG |
| **FRAMEWORK** | SynthesisOutput + 品类 | FrameworkOutput（方法论/结构/入口出口状态） | 方法论不匹配 → 回退 | genres/*/framework.yaml |
| **STYLE** | 品类预设 | StyleOutput（5 维坐标 + 约束） | 无（配置层） | genres/*/style_preset.yaml |
| **PROSODY** | StyleOutput + 品类 | ProsodyOutput（范本 + 节奏提示 + 负约束） | 无（范本层） | genres/*/prosody_samples/ |
| **COMPILE** | 全部层输出 | CompileOutput（markdown + 结构化元数据） | token 超限 → 裁剪素材 | contracts.py |

### 质量体系

#### 硬门控（不通过不发布）

1. **value_density** < 4.0 → slop 拦截
2. **humanizer** < 30/50 → prose 质量过差
3. **fabrication_flags** > 2 → 编造嫌疑
4. **AI 检测** 模式分 < 门槛
5. **"不是...而是..."** 超限（品类调整基准）

#### 加权总分（10 维）

| 维度 | 权重 | 检查内容 |
|------|------|----------|
| value_density | — | 独占信息比（独立评分，硬门控） |
| humanizer | 0.14 | 5 维人味评分 |
| ai_check | 0.10 | 40+ AI 套话模式 |
| dbs_ai | 0.15 | 22 AI 指纹特征（dbskill 集成） |
| fabrication | 0.15 | 编造检测 |
| cross_reference | 0.10 | 事实交叉验证（TIER_EXTERNAL） |
| semantic_facts | 0.08 | cocobook 语义验证 |
| format | 0.05 | 结构完整性 |
| word_count | 0.05 | 字数达标 |
| jargon | 0.10 | 黑话检测 |
| style_compliance | 0.08 | 风格遵循度 |

### 品类体系（21 种）

#### 搜索型（full/subtle injection，INTERNAL）

- tutorial, guide, troubleshooting, comparison, beginner, listicle, resource-roundup, tool-review

#### 相遇型（full/subtle injection，INTERNAL/EXTERNAL）

- opinion, trend, thought-leadership, editorial, case-study, marketing, brand-marketing, soft-article, product-launch

#### 告知型（none injection）

- announcement, news

#### 专题型（full injection，INTERNAL）

- wp-tech, book-knowledge

---

## 与 OVERHAUL-PLAN.md 核对

### Phase 0: 品类域基础设施

| 任务 | 状态 | 产出物 |
|------|------|--------|
| validate_genres.py | ✅ 完成 | 验证脚本 |
| 5 核心品类 × 5 文件 | ✅ 完成 | tutorial, comparison, opinion, beginner, troubleshooting |
| 剩余 16 品类 | ✅ 完成 | 全部 21 品类框架文件存在 |

**验收**: 5 核心品类 render 输出包含正确的指令 → ✅ 通过（已验证）

### Phase 1: Synthesis 层

| 任务 | 状态 | 产出物 |
|------|------|--------|
| synthesis prompt 设计 | ✅ 完成 | 结构化分析 prompt，禁止写散文 |
| 集成到 pipeline.py | ✅ 完成 | research → synthesis → outline 流程 |
| synthesis 质量门控 | ✅ 完成 | confidence < 0.4 → 拦截 |
| value_density 评分（T-013） | ✅ 完成 | review/value_density.py |
| differentiation 字段（T-014） | ✅ 完成 | synthesis 输出包含 |

**验收**: synthesis 输出可被 dataclass 解析，素材不足选题被拦截 → ✅ 通过

### Phase 2: Framework 层

| 任务 | 状态 | 产出物 |
|------|------|--------|
| framework 加载器 | ✅ 完成 | 读 framework.yaml → FrameworkOutput |
| outline prompt 改造 | ⚠️ 部分 | 基于 FrameworkOutput（未完全替换模板） |
| outline 质量评估 | ⚠️ 未完成 | 人工评估待做 |
| 剩余 16 品类 framework.yaml | ✅ 完成 | 21 品类框架文件全部存在 |

**验收**: 5 品类正确加载，outline 体现方法论结构 → ⚠️ 部分通过

### Phase 3: Prosody 层

| 任务 | 状态 | 产出物 |
|------|------|--------|
| 范本库建设 | ✅ 完成 | 21 品类 prosody_samples 目录 |
| 范本分类器 | ✅ 完成 | 按能量/品类选匹配范本 |
| prosody 注入 writer prompt | ✅ 完成 | few-shot + rhythm_hint |
| style_compliance 评分（T-006） | ✅ 完成 | review/style_compliance.py |

**验收**: 每种语感类型有范本，对比产出有差异 → ✅ 通过

### Phase 4: 解耦 + 验证

| 任务 | 状态 | 说明 |
|------|------|------|
| 提取 creative-core 库 | ⏸️ 暂缓 | 单消费者时暂不做，避免错误抽象 |
| Studio 协作契约 | ⏸️ 暂缓 | Phase 5+ 对接时固化 |
| 跑 20 篇文章端到端 | ⏸️ 暂缓 | 待 Phase 1-3 完全验证后 |
| A/B 验证 | ⏸️ 暂缓 | 同上 |

### Phase 5: Studio 协作

| 任务 | 状态 | 说明 |
|------|------|------|
| visual.py | ✅ 代码就绪 | Studio 视觉协作模块（待对接） |
| screenshot.py | ✅ 代码就绪 | Pinchtab 截图自动化 |
| social_card.py | ✅ 代码就绪 | OG/社交卡生成 |
| scheduler.py | ✅ 代码就绪 | 内容日历调度器 |
| xiaohei domain | ⏸️ Studio 侧 | elementary 发 task-request |

---

## ROADMAP 任务核对

### M0: 基础修复（T-001 + T-002）

| ID | 任务 | 状态 |
|----|------|------|
| T-001 | subtle 品类密度/温暖度映射修复 | ✅ 完成 |
| T-002 | genre_rules 优先级修复 | ✅ 完成 |

**验收**: pytest 全绿，subtle render 正确 → ✅ 通过

### MD: 反 slop 基线（T-013 + T-014 + T-015）

| ID | 任务 | 状态 |
|----|------|------|
| T-013 | value_density 评分 | ✅ 完成 |
| T-014 | differentiation 字段 | ✅ 完成 |
| T-015 | unique_claims 字段 | ✅ 完成 |

**验收**: 评分能区分文章 vs slop，发布门控集成 → ✅ 通过

### M1: 风格细化（T-003 + T-004 + T-005）

| ID | 任务 | 状态 |
|----|------|------|
| T-003 | beginner 审美指令调整 | ✅ 完成 |
| T-004 | brand-marketing 审美指令调整 | ✅ 完成 |
| T-005 | 选题过滤器（dbs-benchmark） | ✅ 完成 |

**验收**: 不再出现错误指令，选题过滤合理 → ✅ 通过

### M2: 风格合规（T-006 + T-007 + T-008）

| ID | 任务 | 状态 |
|----|------|------|
| T-006 | style_compliance 评分 | ✅ 完成 |
| T-007 | 映射降级方案 | ✅ 完成 |
| T-008 | 调度器 + NATS 提醒 | ✅ 完成 |

**验收**: review 包含 style_compliance，周一收到提醒 → ✅ 通过

### M3: 远期任务

| ID | 任务 | 状态 | 说明 |
|----|------|------|------|
| T-009 | 优化密度维度 | ⏸️ 待数据 | 需积累 style_compliance 数据 |
| T-010 | 优化温暖度维度 | ⏸️ 待数据 | 同上 |
| T-011 | 创意写作范本库 | ⏸️ 待采购 | 等书籍采购 |
| T-012 | Review UI | ⏸️ 待开发 | 前端任务 |
| T-016 | compile 结构化输出 | ✅ 完成 | CompileOutput 已实现 |
| T-017 | Studio 协作契约 | ⏸️ 设计完成 | 代码就绪，待对接 |
| T-018 | xiaohei domain | ⏸️ Studio 侧 | elementary 可触发 |
| T-019 | 截图自动化 | ✅ 代码就绪 | 待集成 |
| T-020 | OG/社交卡生成 | ✅ 代码就绪 | 待集成 |
| T-021 | 发布决策门控 | ✅ 完成 | compute_publish_gate |

---

## 差距分析

### 已完成核心

- ✅ 5 层级联编译架构
- ✅ 21 品类 × 5 文件契约
- ✅ synthesis 质量门控
- ✅ dbskill 集成（24 代理技能 toolbox）
- ✅ value_density + differentiation + unique_claims 发布门控
- ✅ style_compliance 评分
- ✅ compile 结构化输出（T-016）
- ✅ Studio 协作代码骨架（待对接）

### 待完成

1. **outline prompt 完全基于 FrameworkOutput**（Phase 2 部分）
   - 当前 outline.py 仍使用模板逻辑
   - 需改造为从 FrameworkOutput.structure 生成

2. **style_compliance 数据积累**（T-009/T-010）
   - 需运行 20+ 篇文章收集数据
   - 才能优化 density/warmth 映射

3. **书籍采购**（T-011）
   - 创意写作范本库

4. **Review UI**（T-012）
   - 前端开发

5. **Studio 对接**（Phase 5）
   - NATS 契约实际通信
   - xiaohei prompts 系统（Studio 侧）

---

## 技术债务

1. **genre_rules.yaml 重复定义**
   - 部分规则与 style_preset.yaml 重叠
   - 可在 Phase 4 解耦时统一

2. **范本库质量参差**
   - 部分品类 prosody_samples 内容稀少
   - 需从 chinese-writing topic 提取补充

3. **outline 模板残留**
   - outline.py 仍有硬编码模板逻辑
   - 未完全利用 FrameworkOutput

---

## 下一步建议

### 短期（本次会话）

1. **完善 outline prompt 改造**
   - 修改 outline.py 从 FrameworkOutput 生成
   - 验证 5 核心品类

2. **运行端到端测试**
   - 5 个关键词跑完全流程
   - 收集质量数据

### 中期

1. **数据积累**（T-009/T-010）
   - 运行 20+ 篇文章
   - 优化风格映射

2. **Studio 对接**
   - 与 studio VM 确认 NATS 契约
   - 测试 visual_brief 流程

### 长期

1. **书籍采购**（T-011）
2. **UI 开发**（T-012）
3. **Phase 4 解耦**（第二条管线出现时）

---

*定义版本：0.3.0-current-state*
*核对基准：OVERHAUL-PLAN.md, ROADMAP.md, SYSTEM-DEFINITION.md*
