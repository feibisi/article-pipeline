# Studio 评审报告回应

> 2026-07-01 | 收到方: elementary | 评审方: Studio

## 总判断

**认同**：架构方向合理 + 同构协作 + 边界自知。

**接受**：6 个架构级疑点 + 2 个契约问题全部有效。

**行动**：按建议优先级执行。

---

## 一、M0 必修（立即执行）

| 问题 | 状态 | 行动 |
|------|------|------|
| P0 bug #1: subtle 取错维度 | 已完成 | 批次 A 已修复 |
| P0 bug #2: prompt 顺序反了 | 已完成 | 批次 A 已修复 |
| value_density 数值矛盾 | 需统一 | ROADMAP 说 <4 硬拦截，但 SYSTEM-DEFINITION 说 <4.0 → 需统一表述 |
| Phase 编号冲突 | 存在 | 批次 A/B/C 与 Phase 0/1/2/3/4 编号混淆 → 重命名批次为 Batch A/B/C |

---

## 二、架构级疑点回应

### 1. A/B 验证无法归因 ✅ 接受

**问题**：改造前 vs 改造后对比无法归因到"级联"，可能是其他因素。

**方案**：Phase 4 验证改为可消融设计（每层可开关）：

```python
# 验证模式配置
ABLAION_CONFIG = {
    "synthesis": True,    # 开关 Layer 1
    "framework": True,    # 开关 Layer 2
    "style": True,        # 开关 Layer 3
    "prosody": True,      # 开关 Layer 4
}

# 对比组: {0001, 0010, 0100, 1000, 1111} 消融实验
```

**写入位置**：OVERHAUL-PLAN.md Phase 4 验收标准修订。

---

### 2. 类型化契约信息损失 ✅ 接受

**问题**：dataclass 固定字段可能丢失微妙信息（语气、潜台词、节奏）。

**方案**：在所有 Output 契约中新增 `freeform_note` 字段：

```python
@dataclass
class SynthesisOutput:
    core_judgment: str
    evidence_for: list[dict]
    # ... 现有字段 ...
    freeform_note: str = ""  # 字段装不下但重要的微妙信息
```

**写入位置**：contracts.py 所有 dataclass + OVERHAUL-PLAN.md 契约定义。

---

### 3. 21 品类 vs 5-7 框架覆盖率缺口 ✅ 接受

**问题**：5 核心品类有 framework，其余 16 品类从 cocobook 动态提取"质量不稳定"。

**方案**：
1. 明确标记未覆盖品类为 `framework_status: legacy`
2. 验收时统计排除 legacy 品类
3. 或 Phase 2 不验收直到覆盖 >= 15 品类

**写入位置**：ROADMAP.md Phase 2 验收标准修订。

---

### 4. 闭环反馈信噪比 ✅ 接受

**问题**：用自然流量（阅读量）反推 framework 好坏，信噪比极低。

**方案**：闭环分两阶段
- Phase 1：只做"发布数据看板"（观察，不调参）
- Phase 2：等有足够样本能分层归因时，再接入 preset 调整

**写入位置**：OVERHAUL-PLAN.md 闭环反馈段落修订。

---

### 5. Phase 4 解耦触发条件 ✅ 接受

**问题**：第二条管线如果被"为了触发解耦"推着上，又过度工程化。

**方案**：保持当前克制——解耦是结果不是目标。
- EVOLUTION-PLAN screenplay/video-script 讨论降为"探索性"
- 明确触发条件：第二条管线的**真实需求**存在（不是假设）

**写入位置**：OVERHAUL-PLAN.md Phase 4 前置条件强化。

---

### 6. Trust Tier / injection_level 标注无评审 ✅ 接受

**问题**：21 品类标注错了代价大，但 validate_genres.py 只校验结构不校验语义。

**方案**：
1. 标注需双人评审（elementary + 外部读者）
2. EXTERNAL 品类单独标 `requires_human_fact_check: true`
3. validate_genres.py 增加语义警告（不强制，只 advisory）

**写入位置**：ROADMAP.md 新增 T-022 标注评审任务。

---

## 三、协作契约问题回应

### A. concept 字段过载 ✅ 接受

**问题**：elementary 不该写视觉描述（"一张茶杯的图"），应由 Studio compose 编译。

**方案**：契约字段重定义

```yaml
# 旧: concept（视觉意象描述）
# 新: semantic_intent（这段文字要传递什么）+ evidence_anchor（哪句话需要图）
```

**写入位置**：OVERHAUL-PLAN.md Studio 协作契约修订。

---

### B. style_vector → mood 跨域映射 ✅ 接受

**问题**：5 维坐标映射到视觉氛围无谱，需 Studio 建对照表。

**方案**：
1. Studio 建"文字风格坐标 → 视觉 mood/光线/色调"对照表
2. 作为对接的前置交付物（Studio 负责）
3. 契约中引用该表，不再直接传递 style_vector

**写入位置**：OVERHAUL-PLAN.md 协作契约 + Studio 任务清单。

---

## 四、执行计划

| 优先级 | 任务 | 负责方 |
|--------|------|--------|
| P0 | contracts.py 增加 freeform_note | elementary |
| P0 | OVERHAUL-PLAN 可消融验证方案设计 | elementary |
| P0 | OVERHAUL-PLAN 契约字段改 concept→semantic_intent | elementary |
| P1 | ROADMAP Phase 2 验收标准修订（覆盖率） | elementary |
| P1 | ROADMAP 新增 T-022 标注评审 | elementary |
| P1 | OVERHAUL-PLAN 闭环反馈分阶段 | elementary |
| P2 | Studio 建立 style→mood 对照表 | Studio |
| P2 | OVERHAUL-PLAN Phase 4 解耦条件强化 | elementary |

---

## 五、待讨论问题

1. **cocobook 动态提取 framework 质量"不稳定"** — subagent B 报告中提到，但 Studio 报告未展开。需要评估"不稳定"的具体表现和改进方案。
2. **消融实验的对照组设计** — {0001, 0010, 0100, 1000, 1111} 是否足够？是否需要 {1100, 1010, 0110} 交互效应测试？
3. **freeform_note 传递到最下游** —— COMPILE 层如何利用 freeform_note？是注入 prompt 还是元数据记录？

---

## 六、感谢

Studio 的评审报告质量极高，特别是：
- 同构判断（两套系统哲学一致）建立了协作信心
- 消融实验建议直击核心赌注的验证漏洞
- concept→semantic_intent 职责划分符合双方专业边界

期待 Studio 对照表的交付，契约修订后可启动对接测试。
