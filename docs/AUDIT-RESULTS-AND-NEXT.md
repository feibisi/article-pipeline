# Article Pipeline — 文档审查结果与下一步执行计划

> 2026-07-01 审查 | 供新会话启动时使用

## 审查汇总

三组子代理对全部 7 份文档进行了交叉审查。以下按严重程度排列。

---

## 一、严重问题（阻碍实施，必须先修）

### 1.1 SYSTEM-DEFINITION.md 整体过时

**现状**: 描述旧的线性管线（Research→Outline→Write→Review→Publish），"三层正交"控制模型与级联编译矛盾。单 LLM 假设（GLM-5.1 + Ollama fallback）。
**修复**: 重写为级联编译架构版本。核心模块图改为 5 层 + 品类域 + 质量门控。三层正交改为"五层级联 + 双轨约束"。技术栈补充多 LLM。
**工作量**: 约 60% 内容需重写，保留品类决策树和 Trust Tier 段落。
**任务 ID**: FIX-01

### 1.2 STYLE-SYSTEM.md 过时

**现状**: 仍是"单步注入 writer prompt"模型，无 prosody 层概念，无多 LLM 校准，无双轨约束。
**修复**: 新增"级联中的位置"节（L3 风格编译 + L4 语感注入），补充 model_calibration 段，明确 style = 工程层（硬约束编译），prosody = 创作层（软约束范本）。
**工作量**: 新增 3 节，调整 2 节措辞。
**任务 ID**: FIX-02

### 1.3 数值矛盾

| 指标 | ARCHITECTURE-GAPS | EVOLUTION-PLAN/ROADMAP | 统一为 |
|------|------------------|----------------------|--------|
| value_density 发布门控 | < 4.0 不发布 | > 6.0 方可发布 | **< 4.0 硬拦截（slop）；>= 6.0 推荐发布；4.0~6.0 需人工判断** |
| ai_check 修订门控 | < 4.0 不走 revise | < 6.0 不走 revise | **< 4.0 标记 prompt 失效（不 revise，回溯诊断）；4.0~6.0 正常 revise** |

**修复**: 在 ARCHITECTURE-GAPS、EVOLUTION-PLAN、ROADMAP 三处统一为上述三档模型。
**任务 ID**: FIX-03

### 1.4 Phase 编号冲突

**现状**: OVERHAUL Phase 0-5 = 级联编译构建阶段；ROADMAP "Phase 0/D/1/2" = 风格修复分组。同名不同义。
**修复**: ROADMAP 的分组改名为 "Milestone"（M0/MD/M1/M2），与 OVERHAUL Phase 区分。
**任务 ID**: FIX-04

### 1.5 FrameworkOutput 缺 visual_anchors

**现状**: T-016/T-019 依赖 `FrameworkOutput.visual_anchors` 字段，但 OVERHAUL-PLAN 的 dataclass 定义中没有。
**修复**: 在 OVERHAUL-PLAN 的 FrameworkOutput 定义中正式加入 `visual_anchors: list[dict] | None = None`。
**任务 ID**: FIX-05

### 1.6 T-001/T-002 与 Phase 0 顺序

**现状**: Phase 0 要求"迁移 _PRESETS 到 yaml 等价于硬编码"——如果 bug 未修就迁移，会锁定错误。
**已修复**: T-001/T-002 已在代码中修复（writer.py + style.py）。只需在 OVERHAUL Phase 0 表格中标注"已完成"。
**任务 ID**: FIX-06

### 1.7 ARCHITECTURE-GAPS 总结节过时

**已修复**: 本会话已更新总结节（加入双轨模型、素材策略、架构模型）。需同步到 main。
**任务 ID**: FIX-07（复制 worktree 文件到 main）

---

## 二、设计问题（应修复，不阻碍但会造成混乱）

### 2.1 Layer 5 两种定义

**问题**: 一处说"validated material 最后注入"，另一处说"Compile = 组装 + token 控制"。
**修复**: 统一为"Layer 5 = COMPILE（组装所有层输出为 writer prompt，含素材裁剪和 token 控制）"。validated material 是 compile 的输入之一，不是独立层。
**任务 ID**: FIX-08

### 2.2 differentiation 字段归属

**问题**: SynthesisOutput 定义了 differentiation，但多处称"outline differentiation 字段"。
**修复**: differentiation 在 synthesis 层生成（因为需要 DDG 对比），在 outline 层使用和验证（门控）。两处不矛盾，但需明确"生成于 synthesis，门控在 outline"。
**任务 ID**: FIX-09

### 2.3 两份排期未交叉引用

**问题**: OVERHAUL 实施表 vs EVOLUTION 实施排期 vs ROADMAP 任务列表，三处独立、部分重叠、时间线冲突。
**修复**: ROADMAP 作为唯一执行清单（task-level），OVERHAUL 保留为 phase-level 规划（不含具体时间），EVOLUTION 保留为方向级（季度粒度）。在各文档开头明确分工。
**任务 ID**: FIX-10

### 2.4 类型化契约不完整

**问题**: FrameworkOutput 只有 placeholder，ProsodyOutput 无正式定义，advisory scorers 无类型。
**修复**: 在 OVERHAUL-PLAN 中补全所有 dataclass 定义（含 visual_anchors、feedback 预留字段）。
**任务 ID**: FIX-11

### 2.5 模糊 LLM 评分作为硬门控

**问题**: value_density 含"反直觉度"等需要 NLI/embedding 的子维度，不是纯规则可检查。
**修复**: 在文档中明确标注"LLM 辅助硬门控"类别——区别于纯规则硬门控（句式禁令、字段非空）。承认这类门控有误判可能，需要 confidence 阈值。
**任务 ID**: FIX-12

### 2.6 xiaohei-scenes 重复描述

**问题**: OVERHAUL 和 ROADMAP T-018 内容近乎重复。
**修复**: ROADMAP T-018 保留执行级描述，OVERHAUL 只保留契约级描述 + "详见 ROADMAP T-018"。
**任务 ID**: FIX-13

### 2.7 发布门控缺少统一 owner task

**问题**: T-013/T-014/T-015 各自独立，但"集成到发布决策"没有专属任务。
**修复**: 新增 T-021（发布决策集成），将三个信号汇入 review 的 publish_gate。
**任务 ID**: FIX-14

---

## 三、可并行的子代理任务拆分

以下任务可在新会话中分配给子代理并行处理：

### 批次 A：文档修复（互相独立，可全并行）

| 子代理 | 任务 | 输入 | 输出 | 预计 token |
|--------|------|------|------|-----------|
| fix-sysdef | FIX-01: 重写 SYSTEM-DEFINITION.md | 当前文件 + OVERHAUL-PLAN 架构段 | 新版 SYSTEM-DEFINITION.md | 中 |
| fix-style | FIX-02: 更新 STYLE-SYSTEM.md | 当前文件 + ARCHITECTURE-GAPS 双轨段 | 补充 3 节的 STYLE-SYSTEM.md | 小 |
| fix-numbers | FIX-03+04+06: 数值统一 + Phase 改名 + 标注已完成 | GAPS + EVOLUTION + ROADMAP + OVERHAUL | 4 文件各处数值/命名修正 | 小 |
| fix-contracts | FIX-05+08+09+11: 补全类型化契约 | OVERHAUL-PLAN dataclass 段 | 完整的 4 个 Output dataclass | 小 |
| fix-crossref | FIX-10+13+14: 交叉引用 + 去重 + T-021 | ROADMAP + OVERHAUL + EVOLUTION | 各文档分工声明 + T-021 | 小 |

### 批次 B：基础设施代码实现（依赖批次 A 的契约定义）

| 子代理 | 任务 | 输入 | 输出 |
|--------|------|------|------|
| genres-scaffold | 创建 genres/ 目录结构 + _schema.yaml | OVERHAUL Phase 0 规格 | 21 目录 + schema |
| genres-migrate | 迁移 _genre_rules 到 yaml | writer.py + style.py 硬编码 | 21 genre_rules.yaml + 21 style_preset.yaml |
| contracts-code | 实现 4 个 Output dataclass | OVERHAUL 契约定义 | article_pipeline/contracts.py |
| validate-genres | 编写 validate_genres.py | _schema.yaml | tools/validate_genres.py |
| synthesis-proto | synthesis.py 原型 | OVERHAUL Layer 1 规格 | article_pipeline/synthesis.py |

### 批次 C：验证（依赖批次 B）

| 子代理 | 任务 | 输入 | 输出 |
|--------|------|------|------|
| test-genres | 验证 genres/ 加载等价性 | 迁移后的 yaml + 原硬编码 | pytest 验证脚本 |
| test-synthesis | 验证 synthesis 对 3 个选题的输出 | synthesis.py + 测试选题 | 测试报告 |
| run-article | 跑 1 篇端到端验证当前质量 | pipeline run | 文章产出 + review 分数 |

---

## 四、新会话启动说明

### 环境

```bash
# 工作目录
cd ~/Projects/article-pipeline

# Git 状态
# main HEAD: 8fedbb8（assets/diagrams commit）
# 注意：git 历史有部分对象损坏（worktree 并行写入导致）
# 影响：git log 会报 "Could not read" 错误，但 HEAD 文件完整
# 如需干净历史：可 git rebase --onto 或重新 clone
# 当前工作不受影响

# 关键路径
docs/                          # 设计文档（7 份 + INDEX.md）
article_pipeline/              # Python 源码
assets/diagrams/               # 架构图（JSON + HTML + render.sh）
tests/                         # pytest 测试
```

### 上下文加载顺序

1. 读 `docs/INDEX.md`（文档导航）
2. 读 `docs/OVERHAUL-PLAN.md`（执行方案，含级联架构 + 契约 + Studio 协作）
3. 读 `docs/ARCHITECTURE-GAPS.md` 最后 50 行（总结节）
4. 读本文件（审查结果 + 任务拆分）

### 执行顺序

```
1. 修复 git（可选，git repack 或重新 clone）
2. 批次 A：5 个文档修复子代理并行（约 10 分钟）
3. 验证文档一致性（人工 5 分钟审阅）
4. 批次 B：5 个代码实现子代理并行（约 15 分钟）
5. 批次 C：3 个验证子代理并行
6. 跑 1 篇文章端到端
7. 更新 state.json + HANDOFF.md
```

### 关键决策（已确认，不需要重新讨论）

- 多 LLM 供应商，成本不是约束
- xiaohei-scenes → Studio prompts 新 domain
- 截图先标记位置，后续自动化
- 配图位置在 outline/framework 阶段确定
- archify 本地跑（Node v22），Studio 走 NATS 协作
- 所有内容默认中文
- 工程层（硬约束）保底线，创作层（软约束）提上限

### 验收标准（本轮改造第一阶段）

1. 所有文档无内部矛盾，无过时描述
2. genres/ 目录结构就绪，validate_genres.py 全通过
3. 4 个 Output dataclass 可导入
4. synthesis.py 原型对 3 个选题输出合理判断
5. 1 篇文章端到端跑通（含 value_density 评估）

### 集群记忆引用

| ID | 标题 | 类型 |
|----|------|------|
| #4203 | article-pipeline 不再局限 WP | decision |
| #4204 | 过度工程化教训：4 个月 0 产出 | lesson |
| #4206 | 反 slop 策略 | decision |
| #4207 | 架构缺三层 | decision |
| #4208 | 独立管线 + 共享核心库 | decision |
| #4211 | 双轨约束模型 | decision |
| #4212 | 素材策略三级视觉编译 | decision |

### 注意事项

- `#4204` 过度工程化教训：不要为了完美文档而延迟产出。文档修完立即进入代码实现。
- Phase 0 完成后必须跑文章验证，不等所有 Phase 完成。
- Studio 协作（T-017~T-020）是 P4 待办，当前阶段不实施。
- SYSTEM-DEFINITION 重写时保留品类决策树和 Trust Tier 段落（仍然有效）。
