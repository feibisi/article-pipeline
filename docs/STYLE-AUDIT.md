# 文风格调系统 — 审计报告

> 审计日期: 2026-07-01 | 审计对象: style.py + 设计文档 + writer.py 集成 + review 反馈回路
> 审计范围: 设计合理性、实现正确性、预设值合理性、系统闭环完整性

## 总体评价

设计思路优于大多数 AI 写作系统的做法。用连续坐标系替代离散 if-else 规则是正确方向，注入分层与 Trust Tier 正交设计清醒。但存在实现 bug、设计缺陷和反馈回路断裂问题。

评级: **B+** — 架构正确，实现需修补，反馈回路需闭合。

---

## 一、实现 Bug（P0 — 必须修复）

### BUG-1: subtle 级别取错了维度

**位置**: `style.py:155-157`

**问题**: 设计文档明确说 subtle 应注入 density + edge。但代码取 `instructions[:2]`，而 `render_temperament()` 维度顺序是 density → warmth → energy → register → edge。实际注入的是 density + warmth。

**影响**: 所有 subtle 品类（resource-roundup, tool-review, product-launch, brand-marketing, soft-article, marketing）的风格指令错误。收到的是"情感距离"指令而非"立场强度"指令。

**修复**:
```python
# 当前
instructions[:2]

# 应改为
[instructions[0], instructions[4]]  # density + edge
```

### BUG-2: Prompt 顺序与设计意图相反

**位置**: `writer.py:371`

**问题**: 设计文档说"LLM 对靠后的指令遵循度更高"，因此 genre_rules 应在 style_block 之后（保证体裁硬规则优先级最高）。但实际代码 genre_rules 在前，style_block 在后。

**影响**: 风格指令的优先级高于体裁硬规则，可能导致 LLM 忽略体裁特有约束。

**修复方案二选一**:
- A: 交换顺序（style_block 在前，genre_rules 在后）
- B: 放弃"后面优先"假设，在 prompt 中用明确的优先级声明（"以下规则优先级高于上方风格指令"）

**建议**: 方案 B 更稳健。LLM 对位置的注意力分布不是确定性的，显式声明优先级比依赖位置更可靠。

---

## 二、设计缺陷（P1 — 建议修复）

### DESIGN-1: 审美概念全量注入，不按品类筛选

**问题**: 所有 full 级别品类注入全部 5 条审美概念。但存在直接冲突：

| 审美概念 | 冲突品类 | 冲突原因 |
|---------|---------|---------|
| 意在言外（结尾不总结） | tutorial, beginner | 教程需要明确操作结论 |
| 留白（不解释，留给读者） | beginner | 新手需要逐步解释 |
| 风骨（不用"或许""可能"） | comparison | 对比文需要呈现不确定性 |

**修复**: 为每个品类定义适用的审美子集：

```python
_AESTHETIC_AFFINITY = {
    "tutorial": ["文气", "分寸"],
    "beginner": ["分寸"],
    "opinion": ["风骨", "文气", "意在言外"],
    "comparison": ["分寸", "文气"],
    "troubleshooting": ["分寸", "风骨"],
    # ...
}
```

### DESIGN-2: density 维度名不副实

**问题**: 维度名叫"疏密/Density"（信息密度），但映射规则控制的是段落物理长度。短句可以信息密集（"WordPress 6.5 废弃了 X、Y、Z 三个 hook"），长段可以信息稀薄。

**两种修复路径**:
- A: 改名为"段幅"（paragraph span / brevity），诚实反映实际控制内容
- B: 重写规则让它真的控制信息密度（"每段必须包含至少一个数据/事实/代码" vs "每段只说一件事"）

**建议**: 路径 A 成本低，不影响已有预设值和映射。路径 B 更正确但需要重新验证所有品类产出。

### DESIGN-3: Humanizer → Style 维度映射为虚假对齐

**位置**: `style.py:244-250`, `STYLE_TO_HUMANIZER`

**问题**: 强行 1:1 映射两个测量目标不同的系统。

| 映射 | 问题 |
|------|------|
| warmth → 信任度 | 冷峻数据文章信任度可以很高 |
| register → 精炼度 | 口语可以简洁，书面可以啰嗦 |
| edge → 真实性 | 强观点模板句反而更像 AI |

**影响**: 让使用者产生错误预期——以为提高 warmth 就能提高"信任度"评分。

**修复**: 将 `STYLE_TO_HUMANIZER` 降级为参考信息（非因果关系），并在文档和 review 输出中明确标注。长期方案：新增独立的 `check_style_compliance()` 评分维度。

---

## 三、预设值可疑（P2 — 建议调整）

### PRESET-1: brand-marketing edge=+0.6 过高

**现状**: +0.6 生成"有明确判断并给出理由"趋向"判断前置"。
**问题**: 品牌营销的 genre_rules 明确说"正文至少 60% 讲行业问题，只有最后一段提自己"——克制、收敛的调性与 +0.6 edge 矛盾。
**建议**: 降到 +0.2 ~ +0.3。

### PRESET-2: soft-article warmth=+0.5 + edge=+0.3 暴露意图

**现状**: warmth=+0.5 生成"用'我们'构建共同体验"。
**问题**: 软文核心规则是"读者前三秒不能察觉是广告"。过暖的语气让读者感觉被推销。
**建议**: warmth 降到 +0.1 ~ +0.2，用事实密度（density 调高）建立权威而非亲近感拉拢。

### PRESET-3: beginner density=-0.4 与详细步骤冲突

**现状**: -0.4 映射到"段落偏短，信息点到为止"。
**问题**: beginner 的 genre_rules 要求"每步带截图描述或精确菜单路径"，这些天然就长。
**建议**: density 调到 -0.1 ~ +0.1（中性），让段落长度由内容决定而非被风格强制限短。

---

## 四、反馈回路断裂（P1 — 架构级问题）

### LOOP-1: 缺少风格遵循度评分

**现状**: style 系统生成指令 → LLM 可能遵循也可能忽略 → review 不检查是否遵循。

**影响**: 无法知道风格指令是否真的影响了产出。无法迭代改进预设值。

**建议**: 在 review 模块新增 `check_style_compliance(article, vector)`：
- 检查人称使用（warmth 指令）
- 检查段落长度分布（density 指令）
- 检查判断句位置（edge 指令）
- 输出遵循度分数（0-10）

### LOOP-2: overall_score 权重不反映风格质量

**现状**: humanizer 权重最高 (0.27)，但它测量"像不像人"，不是"风格是否到位"。

**影响**: 一篇文章可以通过 humanizer（不像 AI）但完全忽略风格指令。overall_score 无法反映风格系统的有效性。

**建议**: 新增 style_compliance 维度，分配 0.08~0.10 权重（从 humanizer 分出）。

---

## 五、测试覆盖缺口

| 覆盖了 | 未覆盖 |
|--------|--------|
| StyleVector 创建与验证 | 端到端 prompt 组装正确性 |
| preset 获取与 fallback | subtle 取的是哪两个维度（bug 遮蔽） |
| render 输出格式 | 审美概念与 genre_rules 冲突检测 |
| injection 分级行为 | 不同 LLM 对指令的实际遵循度 |
| humanizer 映射完整性 | style override 在完整 pipeline 中的效果 |

---

## 六、改进路线图

| 阶段 | 内容 | 预计工作量 |
|------|------|-----------|
| Phase 0 (立即) | 修 BUG-1 subtle 维度选取 + BUG-2 prompt 顺序 | 0.5h |
| Phase 1 (本周) | 审美概念品类适配 + preset 调整 (3 个品类) | 2h |
| Phase 2 (本月) | 新增 check_style_compliance() + 权重调整 | 4h |
| Phase 3 (后续) | density 维度重定义 + humanizer 映射降级 | 2h |
| Phase 4 (观察) | 积累数据后评估是否进入 genre_rules 替换 | 持续 |

---

## 七、对这套系统的整体判断

这是一个**工程上做对了方向、但在"模型真的能听懂多精细的写作指令"这个问题上高估了 LLM 能力**的系统。

5 维坐标精度是 0.1 级别（21 个品类中有多对品类坐标差异小于 0.2），但当前 LLM 对这个精度不敏感。实际有效的是跨区间调整（从"冷"到"暖"），而非区间内微调。

**坐标系最大的价值不是精确控制 LLM，而是给人类编辑一个可调参的界面。** 当 review_server UI 让编辑能看到"这篇 warmth 偏暖了，调低重写"时，坐标才真正有用。当前纯自动化场景下，它更像一个精密旋钮接在一个粗糙执行器上。

**务实建议**: 把 4 个区间简化为 3 个（低/中/高），放弃 0.1 精度的假象，把精力放在审美概念的品类适配和风格遵循度评分上——这两个对产出质量的影响远大于坐标精度。
