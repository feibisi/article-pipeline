# Article Pipeline — 任务计划

> 更新: 2026-07-01 | 状态追踪: elementary VM state.json

## 当前状态

- Pipeline v0.3.0 已跑通全链路（research → outline → write → review → publish）
- Style System 已实现并集成，但有 2 个实现 bug
- Trust Tier 双轨已上线，EXTERNAL 人工闸门已生效
- Review 10 维评分已完整，review_server UI 可用
- 内容日历已制定（modiqi），但未对接自动调度
- 已发布 5 篇教程到文派社区（2026-03-14）
- 选题过滤器已设计未实现（2026-06-01 决策）
- 文风格调系统审计完成，发现 2 bug + 3 设计缺陷

## 任务优先级

### P0 — 立即修复（阻碍系统正确运行）

#### T-001: 修复 subtle 级别维度选取 bug
- **文件**: `article_pipeline/style.py:155-157`
- **问题**: `instructions[:2]` 取了 density + warmth，设计要求取 density + edge
- **修复**: 改为 `[instructions[0], instructions[4]]`
- **影响**: 6 个 subtle 品类的风格指令全部错误
- **验证**: `pytest tests/test_article_pipeline/test_style.py -k subtle` + 手动检查输出

#### T-002: 修复 prompt 顺序/优先级声明
- **文件**: `article_pipeline/writer.py:371`
- **问题**: genre_rules 在 style_block 前面，与"后面优先级更高"的设计意图矛盾
- **方案**: 在 genre_rules 块开头加显式优先级声明："以下体裁规则优先级高于上方风格指令，冲突时以此为准。"
- **验证**: 对比修改前后同一 keyword 的产出差异

### P1 — 本周完成（显著提升产出质量）

#### T-003: 审美概念品类适配
- **文件**: `article_pipeline/style.py` 的 `render_aesthetic_concepts()`
- **方案**: 新增 `_AESTHETIC_AFFINITY` 映射表，每个品类只注入适合的审美子集
- **关键适配**:
  - beginner: 只保留"分寸"（精确描述）
  - tutorial: "文气"+"分寸"（节奏+精确）
  - opinion/editorial: "风骨"+"文气"+"意在言外"（全套判断力）
  - comparison: "分寸"+"文气"（精确+节奏）
  - troubleshooting: "分寸"+"风骨"（精确+果断）
  - case-study: "文气"+"意在言外"（叙事节奏+开放结尾）
- **验证**: 修改后 render_style_block() 对 beginner 不再输出"留白""意在言外"

#### T-004: 调整 3 个品类预设值
- **文件**: `article_pipeline/style.py` 的 `_PRESETS`
- **变更**:
  - brand-marketing: edge 从 +0.6 降到 +0.3
  - soft-article: warmth 从 +0.5 降到 +0.2, density 从 +0.0 升到 +0.3
  - beginner: density 从 -0.4 升到 +0.0
- **验证**: 各写一篇文章，人工评估是否更符合品类定位

#### T-005: 选题过滤器实现
- **来源**: 集群记忆 #3503（2026-06-01 决策）
- **位置**: 新建 `article_pipeline/topic_filter.py`
- **逻辑**: 每条 keyword 入队前跑三个 check:
  1. 近三月同质文章数量（DDG 搜索 + 结果计数）
  2. 有没有一个主流观点可能是错的（cocobook 搜索矛盾证据）
  3. 研究素材里有没有反直觉数据
- **规则**: 三个 check 全否 → 标记为 low_value，不自动排入队列
- **集成点**: `article-pipeline add` 命令中调用，输出过滤建议
- **验证**: 用 10 个已发布文章的 keyword 回测，看过滤器是否合理

### P2 — 本月完成（系统闭环）

#### T-006: 新增 check_style_compliance() 评分
- **位置**: `article_pipeline/review/__init__.py`
- **方案**: 基于规则检查文章是否遵循了风格指令
  - warmth 指令 → 检查人称使用频率（"你"/"我们"/第三人称）
  - density 指令 → 检查段落平均长度分布
  - energy 指令 → 检查短句/长句比例、反问句频率
  - edge 指令 → 检查判断句位置（是否前置）、确定性词汇密度
  - register 指令 → 检查口语词/书面词比例
- **输出**: 0-10 分，加入 overall_score（权重 0.08，从 humanizer 分出）
- **验证**: 用已发布文章跑 check_style_compliance，验证分数分布合理

#### T-007: STYLE_TO_HUMANIZER 映射降级
- **文件**: `article_pipeline/style.py`, `article_pipeline/review/__init__.py`
- **方案**: 在 review 结果中将 `style_humanizer_map` 标注为"参考映射（非因果）"，review_server UI 中加注释说明
- **不需要删代码**: 保留映射，但改变呈现方式

#### T-008: 内容日历 → pipeline 调度对接
- **来源**: 集群记忆 #2932（modiqi 制定的内容节奏）
- **方案**: 新建 `article_pipeline/scheduler.py`
  - 读取配置中的发布节奏（平台 → 频率）
  - 每周一自动检查队列是否有足够选题覆盖本周计划
  - 不足时通过 NATS 通知 modiqi："本周 wpcommunity 缺 1 篇选题"
- **不自动添加选题**: 调度器只做提醒，选题仍需人工/过滤器确认

### P3 — 后续迭代（优化与扩展）

#### T-009: density 维度重定义
- 评估两条路径（改名 vs 重写规则），选择后实施
- 需要先积累 T-006 的 style_compliance 数据再决定

#### T-010: 区间简化为 3 级
- 将 4 区间（-1~-0.5, -0.5~0, 0~+0.5, +0.5~+1）合并为 3 级（低/中/高）
- 需要先验证当前 4 区间中哪些相邻区间在 LLM 产出中确实无区别
- 依赖 T-006 数据

#### T-011: 创意写作独立 workspace
- **来源**: 集群记忆 #3504（2026-06-01 决策）
- **前置**: 采购剧作理论书（麦基/坎贝尔/斯奈德）
- **内容**: 新建 `~/workspaces/creative-writing/`，独立 CLAUDE.md/评价标准/素材库
- **与 article-pipeline 关系**: 完全独立，不共享 pipeline 代码

#### T-012: review_server UI 增强
- 风格坐标可视化（雷达图）
- style_compliance 分数展示
- 一键调整风格坐标并重写
- 版本间风格对比

---

## 依赖关系

```
T-001 ─┐
T-002 ─┼─→ T-004（预设调整需要在 bug 修复后验证）
T-003 ─┘
        └─→ T-006（compliance 评分需要正确的风格指令作为基线）
              └─→ T-009, T-010（维度优化需要 compliance 数据）

T-005 (选题过滤器) — 独立，无依赖
T-007 (映射降级) — 独立，无依赖
T-008 (调度器) — 独立，T-005 完成后效果更好
T-011 (创意写作) — 独立，等书籍采购
T-012 (UI) — 依赖 T-006
```

## 验收标准

### Phase 0 完成标志（T-001 + T-002）
- `pytest tests/` 全绿
- subtle 品类 render 输出包含 density + edge 指令（而非 density + warmth）
- 对同一 keyword 写两版文章（修复前/后），genre_rules 在冲突时被 LLM 优先遵循

### Phase 1 完成标志（T-003 + T-004 + T-005）
- beginner 文章不再出现"结尾不总结全文"的审美指令
- brand-marketing 文章不再出现过于犀利的判断句
- 选题过滤器对 10 个测试 keyword 输出合理的过滤建议

### Phase 2 完成标志（T-006 + T-007 + T-008）
- review 结果中有 style_compliance 分数
- overall_score 公式包含 style_compliance 权重
- 每周一能收到选题缺口提醒（NATS 消息）
