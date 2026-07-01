# Article Pipeline — 架构缺层分析与重构方向

> 2026-07-01 | 本文档记录管线的结构性缺陷，不是优化建议，是缺层诊断。

## 核心问题：写作的本质是什么

写作 = 我理解了一件事，把这个理解传递给你。

前提是"我理解了"。没有理解就没有写作，只有文字搬运。当前管线缺的不是更好的句式检测或更精确的风格坐标，缺的是**理解能力本身**。

---

## 元问题：LLM 为什么写出来像 AI

这不是 bug，是架构必然。理解根因才能在正确的层干预。

### 六个结构性原因

#### 1. 下一个 token 预测优化概率，不优化好

LLM 每次选最可能的下一个词。"最可能"= 训练数据中最常见的模式。常见 = 平庸（平庸文本在互联网上数量碾压好文本）。

后果：高频模板句（如"值得注意的是"）被选中，因为它们统计上最安全。

#### 2. RLHF 训练了讨好而非表达

模型被训练为 helpful + harmless + honest，制造了：
- **hedge 倾向** — "X有优点也有缺点"（不选边 = 安全 = 高人类评分）
- **过度解释** — 每句话补充说明（怕你没懂 = helpful）
- **均衡覆盖** — 列举所有角度而非深入一个（全面 = 好评）
- **正式化漂移** — 像论文不像人话（正式 = 显得专业 = 高评分）

#### 3. 逐 token 生成看不到全局节奏

人类写完一段会回头看："这里需要一个短句断一下"。LLM 不回头。

后果：段落节奏单调、无长短交替的自觉、连接词过度（每句都要跟前一句接上，不知道可以不接）。

#### 4. 没有信息不对称感知

人类作者知道"读者不知道这个，我告诉他会有效果"。LLM 把所有信息视为等权重。

后果：没有悬念（不铺垫）、没有取舍（不判断什么可以不说）、没有克制。

#### 5. 没有删除过程

人类：写 → 删 → 改 → 再删。好文章是删出来的。LLM 只追加。

后果：每段比需要的长、过渡句是填充物、不会"说完就停"。

#### 6. 无身体经验的抽象漂移

写"我测了，TTFB 多了 8ms"需要真的测过。LLM 没测过任何东西。

后果：默认抽象描述（"根据实际测试数据显示"）而非具体经历（"上周部署时踩了这个坑"）。

### 每个原因对应的干预层

| LLM 特性 | 导致的问题 | 应对层 | 具体干预 |
|----------|-----------|--------|---------|
| 概率优化 → 平庸模板 | 高频句式 | Prosody（L4） | negative constraints + 低频范本 few-shot |
| RLHF → 讨好/hedge | 不选边、均衡废话 | Synthesis（L1） | 强制输出 core_judgment（必须选边） |
| 逐 token → 节奏单调 | 无长短交替 | Prosody（L4） | 范本驱动 + rhythm_hint |
| 无信息不对称 | 无悬念/取舍 | Framework（L2） | 方法论强制信息排序（铺垫→揭示） |
| 无删除过程 | 过长/填充 | Review + Style | avoid 列表 + word_budget per section |
| 无身体经验 | 抽象漂移 | Synthesis（L1） | unique_claims 标记具体经历/数据 |

### 关键洞察

**大部分 AI 味不是句式问题（表层），是思维模式问题（深层）。**

Negative constraints 能解决原因 1（禁止高频模板），但解决不了 2-6。禁止某个句式后，模型还是会用另一种方式 hedge，因为 hedge 是 RLHF 训进去的行为模式。

真正有效的干预是在写作之前就让系统做了人类作者才会做的事：
- 选边（synthesis 的 core_judgment）— 对抗 RLHF 的 hedge 倾向
- 取舍（framework 的 word_budget + 段落职责分配）— 对抗无删除过程
- 有具体经历（synthesis 的 unique_claims）— 对抗抽象漂移
- 知道什么不说（style 的 avoid + outline 的显式删除）— 对抗均衡覆盖
- 控制节奏（prosody 范本 few-shot）— 对抗逐 token 节奏失控

这些都不是写作阶段能解决的。等到 writer prompt 时已经晚了，模型已经在用它的默认行为模式了。级联编译的价值正在于此：**在写之前，用结构化约束预先替模型做了它做不了的决定**。

### 对风格系统的启示

风格系统的 5 维坐标，本质上是在跟 LLM 的默认行为模式对抗：

| 坐标 | 对抗什么 | 当前做法（弱） | 改造后做法（强） |
|------|---------|---------------|----------------|
| edge | RLHF 的 hedge | "请写得犀利一些" | require: 判断句前置; avoid: "各有优劣"类结论 |
| warmth | RLHF 的正式化漂移 | "请写得温暖" | require: 使用"你"; avoid: 全第三人称叙述 |
| energy | 逐 token 节奏失控 | "请写得有节奏" | require: 短句占比>40%; avoid: 连续3句等长 |
| register | 正式化漂移 | "请口语化" | require: 口语标记词; avoid: "综上所述"类书面词 |
| density | 无删除过程的膨胀 | "请写得精炼" | word_budget per section; avoid: 无新信息的过渡句 |

散文指令（"请写得犀利"）无法对抗 RLHF 级别的行为偏好。结构化约束（require/avoid + 可验证检查）才能。

---

## 风格系统改造定义

### 改造后的定义

**创作人格的结构化编码层。**

不是"让文章好听的指令生成器"，不是"品类模板选择器"，不是"语感控制器"。

它只做一件事：定义"这个创作者是谁"，然后把这个定义编译成任何格式引擎能消费的结构化约束。

```
输入: 5 维坐标值（创作者人格的数学表达）
输出: {purpose, require, allow, avoid}（机器可检查的行为边界）
```

### 当前最大设计错误

将风格系统当作"prompt 美化器"使用。`render_style_block()` 输出散文指令塞进 writer prompt，LLM 自由解读，结果不可控。

Studio 不会把品牌规范写成一段话让模型"自行理解"，而是用结构化的 banned/required 列表，机器可检查。

### 改造后的输出

`render_style_block()` 输出两样东西：
1. **结构化约束**（给 review 模块做合规检查，机器可验证）
2. **渲染后的文本指令**（给 LLM 参考，辅助手段，不是唯一控制）

Review 从"事后打分"变为"检查产出是否符合 require 并避开了 avoid"。

### 5 维坐标编译规则

保留 5 维，正确的抽象层级，足够通用能跨格式，又足够具体能映射到行为。但每个维度重新定义编译规则：

| 维度 | 编译为 require | 编译为 avoid | 可量化检查 |
|------|---------------|-------------|-----------|
| density | 每百字至少 N 个新信息点 | 无新信息的过渡句、重复表述 | 信息点密度统计 |
| warmth(+) | 使用"你"直接对话 | 全第三人称无温度叙述 | 人称词频 |
| warmth(-) | 客观中立陈述 | 过度亲昵/口头禅 | 人称词频 |
| energy(+) | 短句占比>40%、段落间无缓冲 | 连续3句等长、每段首句"接下来" | 句长分布 |
| energy(-) | 从容铺陈、段落有呼吸 | 短句堆砌制造假紧迫感 | 句长方差 |
| register(+) | 口语标记词、不完整句 | "综上所述"类书面连接词 | 标记词频率 |
| register(-) | 书面正式用词 | 过度口语/网络用语 | 标记词频率 |
| edge(+) | 判断句前置、确定性表述 | "各有优劣"类 hedge 结论 | 判断句位置+确定性词密度 |
| edge(-) | 保留开放性、呈现多面 | 过度断言无依据 | 确定性词密度 |

每个维度不再输出散文"请写得更有温度"，而是输出具体的 require/avoid 项，下游可验证。

### 与 Studio 品牌系统的关系

```
品牌 identity（共享）
  ├→ 风格系统 → {require/allow/avoid} for 文本    ← elementary
  └→ art-direction → {require/allow/avoid} for 视觉 ← studio
```

平行结构，共享品牌 identity，各自编译到各自的输出域。

---

## 当前架构 vs 正确架构

```
当前架构:
  keyword → [research: 收集碎片] → [outline: 套模板] → [writer: 同时理解+组织+表达] → 文章

目标架构:
  keyword → [research: 收集碎片]
         → [synthesis: 从碎片形成理解]
         → [framework: 选择论证/组织方法]
         → [outline: 基于理解+框架搭骨架]
         → [writer: 只管表达]
         → 文章
```

writer 当前同时承担四个职责：
1. 从碎片中理解话题（认知负载）
2. 发现碎片间的关系（分析负载）
3. 形成立场/角度（判断负载）
4. 写成文章（表达负载）

LLM 在同时承担这四项时，会选最省力的路径，串碎片、加连接词、输出通顺但空洞的文章。这就是为什么产出"读着像那么回事但没有新东西"。

---

## 缺层一：Synthesis（理解/综合）

### 位置
research 之后，outline 之前。

### 职责
把素材碎片转化为对话题的结构化理解。

### 输入
`gather_research()` 的输出（cocobook 标注、书籍段落、网络文章、topic 索引段落）

### 输出
一个结构化的"理解文档"：

```yaml
topic: "WordPress Object Cache"
core_judgment: "小站点用 Redis Object Cache 是反优化，中大站点才有收益"
evidence_for:
  - source: "《高性能 WordPress》ch7"
    claim: "Object Cache 的价值与查询复杂度正相关，简单站点几乎无收益"
  - source: "elementary 实测"
    claim: "5 个插件的小站，开启 Redis 后 TTFB 反而多了 8ms（序列化开销）"
evidence_against:
  - source: "官方文档"
    claim: "推荐所有站点启用 persistent object cache"
  - source: "网络主流观点"
    claim: "Redis 是 WordPress 性能优化标配"
resolution: "分歧在于站点规模。官方推荐面向中大型站点，但社区复读时丢失了前提条件"
unique_angle: "量化'多大算大'的阈值，从实测数据给出具体数字"
```

### 这一层的核心操作

| 操作 | 说明 | 当前是否存在 |
|------|------|-------------|
| 对比 | 多来源对同一话题的不同说法 | 不存在 |
| 矛盾检测 | 书 A 和书 B 的建议是否冲突 | 不存在 |
| 共识提取 | 所有来源一致认同的是什么 | 不存在 |
| 立场形成 | 基于证据选边，说清楚为什么 | 不存在 |
| 独特性标记 | 哪些发现是搜索结果里没有的 | 不存在 |

### 实现方式

不需要复杂的 NLI 模型。一次 LLM 调用，prompt 结构化要求：

```
你是一个研究分析师。以下是关于 [keyword] 的多来源素材。
不要写文章。做以下分析：

1. 核心共识：所有来源都同意什么？
2. 分歧点：哪些来源互相矛盾？矛盾的具体内容是什么？
3. 你的判断：基于证据，哪边更对？为什么？
4. 独特发现：哪些 claim 只出现在一个来源里（搜索引擎上找不到）？
5. 核心判断：用一句话说清楚"这篇文章要传递什么理解"

[素材...]
```

关键约束：这一步用的模型可以比写作模型弱（分析能力 vs 表达能力是不同维度），但 prompt 必须禁止它写散文，只输出结构化数据。

### cocobook 在这一层的真正价值

cocobook 存的不是"素材"，是"作者已经消化过的理解"。书和网页的区别：

- 网页：一个人花 30 分钟写的，可能是搜索结果的改写
- 书：一个人花 1-3 年写的，做了选择（什么重要什么不重要、什么因导致什么果）

当 synthesis 模块发现 cocobook 标注说"X 是反优化"而网上普遍说"X 是标配"时，这个矛盾本身就是文章的独特价值。矛盾已经存在于知识库中，只需要检测出来。

---

## 缺层二：Framework（方法论/写作框架）

### 位置
synthesis 之后，outline 之前（或作为 outline 的前置逻辑）。

### 当前 outline 的问题

当前 `outline.py` 的 OUTLINE_PROMPT 按品类选结构模板：
- 搜索型 → "问题 → 原因 → 解决方案 → 总结"
- 相遇型 → "钩子 → 故事 → 论点 → 行动号召"
- 告知型 → "核心消息 → 细节 → 影响"

这是**格式**框架，不是**方法论**框架。它告诉 outline "用什么结构装内容"，但不告诉它"内容怎么组织才有说服力"。

### 什么是方法论框架

| 品类 | 格式框架（当前有的） | 方法论框架（缺的） |
|------|---------------------|-------------------|
| tutorial | H2 分步骤 | 认知脚手架：先给全貌建心理模型，再拆步骤，每步说清楚"为什么这一步在这里" |
| comparison | 表格对比 | 评估方法论：先统一维度定义，再逐维度对比，最后给决策树而非"各有优劣" |
| opinion | 论点 + 论据 | 论证结构：先承认对方合理性（铺垫），找到对方论证的隐含假设，翻转这个假设 |
| troubleshooting | 问题 → 解决 | 诊断方法：症状分类 → 排除法缩小范围 → 根因定位 → 解决，不是"试试 A，不行试 B" |
| case-study | 时间线叙事 | 经验萃取：不只是"我做了什么"，而是"什么条件下什么决策导致什么结果，可迁移的规律是什么" |

### cocobook 写作方法论的正确用法

当前 `writing_craft` 搜索出来的段落被当成"语感范本"喂给 writer。但如果一本讲论证的书说"论证要先给出对方最强的 steel-man 版本再反驳"，这不是让 writer 学它的句式，是告诉 framework 层"opinion 类文章的论证应该用 steel-man + 反驳 结构"。

正确用法：
- 在 framework 层从 cocobook 写作类标注中提取品类相关的**组织方法**
- 把方法作为 outline 的组织原则（不是模板槽位）
- writer 拿到的 outline 已经内含了方法论（因为骨架本身就体现了论证逻辑）

### 实现方式

两种路径：

**路径 A：预提取 + 硬编码**
从 cocobook 写作类书籍中人工提取每个品类的方法论，硬编码为 `GENRE_FRAMEWORKS` 常量。优点：确定性高，不依赖 LLM 提取。缺点：覆盖有限，新品类需手动维护。

**路径 B：动态检索**
outline 阶段先搜 `chinese-writing` topic 中与品类相关的方法论段落，用 LLM 从中提取组织原则，再基于原则生成 outline。优点：灵活，知识库更新即生效。缺点：多一次 LLM 调用，提取质量不稳定。

建议：先 A 后 B。Phase 1 硬编码 5-7 个核心品类的方法论框架（tutorial/comparison/opinion/troubleshooting/case-study/guide/editorial），验证效果后再做动态检索。

---

## 缺层三：语感（Prosody）vs 风格（Style）

### 当前混淆

5 维坐标系（density/warmth/energy/register/edge）管的是**态度/人格**：
- 冷暖 = 对读者的距离感
- 锐钝 = 下判断的确定性
- 动静 = 是推进还是铺陈
- 雅俗 = 用词的正式程度
- 疏密 = 信息压缩程度

这些定义的是"作者是什么人"，一个温暖、果断、节奏快、口语化、信息密集的人。

但这不是"文章读起来什么感觉"。语感是物理层的东西：

### 语感的构成

| 层面 | 具体表现 | 当前系统管不管 |
|------|---------|---------------|
| 句子节奏 | 长短句怎么交替（短-短-长-短 vs 长-长-短） | 不管 |
| 段落呼吸 | 段落在哪里留白、什么时候转换节奏 | 不管 |
| 句间承接 | "但" vs "不过" vs 直接转折无连接词 | 不管（register 维度只管正式/非正式） |
| 信息节奏 | 关键判断放句首还是句尾（前置 vs 铺垫揭示） | 不管（edge 管确定性，不管位置） |
| 声音质感 | 用词的音节感（"碾压"vs"胜过"，单纯语义同义但听感不同） | 完全不管 |

### 为什么 5 维坐标管不了语感

例子：两段话同样是 `warmth:+0.5, energy:+0.7, edge:+0.6`

```
版本 A（有语感）:
Redis 在小站上是反优化。我测了。开启前 TTFB 180ms，开启后 188ms。
序列化开销吃掉了缓存收益。
不是所有网上说的"标配"都适合你。

版本 B（无语感，但符合同一坐标）:
在小型 WordPress 站点上，Redis Object Cache 的效果可能适得其反。
根据我的实际测试数据显示，启用前 TTFB 为 180 毫秒，启用后反而增加到了 188 毫秒。
这主要是因为序列化操作的开销抵消了缓存带来的收益。
因此，网络上所谓的"标配建议"并不一定适用于所有场景。
```

版本 B 技术上满足了所有维度要求（有温度、有力度、有判断），但读起来像翻译腔。区别在于：
- A 用不完整句（"我测了。"）制造节奏断裂
- A 用极短句跟长句交替
- A 最后一句直接跟读者说话，不用"因此"铺垫
- A 不用"根据...数据显示"这种信息密度为零的官方叙述词

### 语感怎么实现

这是最难的部分。三个层次：

**层次 1：负面约束（已启动，S4）**

禁止 AI 常见的语感杀手：
- 破折号解释补充
- "根据...数据显示"
- "值得注意的是"
- 过度连接词（"因此""所以""然而"每段都用）
- 逗号链长句

这能消除最坏的情况，但不能产生好的语感。

**层次 2：范本驱动（可实现）**

从 cocobook `chinese-writing` topic 中提取不同语感类型的真实段落，作为 few-shot 示例给 writer：

```
写作时模仿以下段落的节奏和句间关系（不是内容，是写法）：

[范本段落 1 — 短句推进型]
"Redis 在小站上是反优化。我测了。..."

[范本段落 2 — 铺垫揭示型]
"所有人都在推荐 Redis。文档推荐，教程推荐，Stack Overflow 推荐。..."
```

这比抽象的"请写得有节奏感"有效得多，LLM 对具体范本的模仿能力远强于对抽象指令的遵循。

但范本的选择需要跟品类/风格坐标匹配。`energy:+0.7` 应该给短句推进型范本，`energy:-0.3` 应该给从容铺陈型范本。

**层次 3：语感维度独立建模（长期）**

在 5 维坐标之外新增语感轴：

| 维度 | 两极 | 例子 |
|------|------|------|
| 句式节奏 | 均匀 ↔ 断裂 | 均匀=每句差不多长，断裂=长短急剧交替 |
| 叙述距离 | 全知 ↔ 现场 | 全知="这意味着..."，现场="我打开终端，运行了..." |
| 连接显隐 | 显式 ↔ 隐式 | 显式="因此/然而"，隐式=并列无连词读者自己推 |

但这需要先有层次 2 的数据验证哪些语感维度对 LLM 产出确实有区分度，否则又是拍脑袋建模。

---

## 三层缺失的关系

```
synthesis → 解决"写什么"（有没有理解）
framework → 解决"怎么组织"（有没有方法论）
prosody   → 解决"读起来什么感觉"（有没有语感）

三者独立，不互相依赖。可以分别推进。
但优先级明确：synthesis > framework > prosody
因为：有理解但表达一般 > 没理解但很流畅
```

## 与现有模块的关系

| 新增层 | 输入来源 | 输出消费者 | 对现有模块的改动 |
|--------|---------|-----------|----------------|
| synthesis | research 的 sources dict | outline (核心判断 + 素材关系) | research 不变，outline prompt 改为接收 synthesis 输出 |
| framework | synthesis + cocobook writing-craft | outline (组织原则) | outline prompt 从"按品类套模板"改为"按方法论组织" |
| prosody | style 坐标 + 品类 | writer (few-shot 范本) | style.py 新增范本选择逻辑，writer prompt 新增范本段 |

## 实施路径

### Phase 0（立即可做）
- 在 outline.py 的 OUTLINE_PROMPT 中加入 differentiation 字段（T-014，已规划）
- 硬编码 5 个核心品类的方法论框架到 outline prompt

### Phase 1（1-2 周）
- 新建 `article_pipeline/synthesis.py`
- 实现基础版本：一次 LLM 调用，输入素材，输出结构化理解
- pipeline.py 流程改为 research → synthesis → outline → write
- 验证：同一选题，有 synthesis vs 无 synthesis 的文章对比

### Phase 2（2-4 周）
- framework 层从 cocobook writing-craft 预提取 5 个品类的方法论
- outline 改为方法论驱动而非模板驱动
- 验证：outline 质量对比（模板版 vs 方法论版）

### Phase 3（月 2+）
- prosody 层次 2：范本驱动语感
- 建立范本库（从 chinese-writing topic 中按语感类型分类）
- style 坐标 → 范本选择映射
- 验证：同坐标不同范本的产出语感差异

---

## 与之前规划的关系

本文档定义的三层缺失是比 ROADMAP 中 T-001~T-015 更深层的问题。T-013（value_density）和 T-014（differentiation）是 synthesis 层的前置信号，如果 synthesis 层做好了，value_density 自然会高，因为文章有独占判断。

但不应该等 synthesis 做完才启动 T-013/T-014。它们的价值在于**立即建立评判标准**，先知道"什么算好"，再去造"好"。

优先级排序：
1. T-013/T-014（建立标准）— 本周
2. synthesis.py 基础版（建立理解能力）— 下周
3. framework 硬编码版（建立组织方法）— 第 3 周
4. prosody 范本驱动（建立语感）— 第 2 个月

EVOLUTION-PLAN.md 的 Path A/B/C/D 保持不变，本文档描述的是比它们更底层的架构重构。

---

## 风格系统解耦：从 article-pipeline 专属到通用创作基础设施

### 背景

文风格调系统（5 维坐标）不是为"写文章"设计的。它定义的是**创作者人格**，这个人写文章是这样，写剧本也是这样，写小说还是这样。当前它被硬编码在 `article_pipeline/style.py` 里，但它的设计本质是跨格式的。

未来架构：

```
              风格系统（通用创作人格控制）
                      |
      ┌───────────────┼───────────────┐───────────
      |               |               |
   文章管线        剧本管线        小说管线        短视频脚本...
   (research      (场景构建      (世界观构建     (脚本结构
    synthesis      冲突设计       人物弧光        分镜逻辑
    outline        节拍表         情节结构        画面描述
    write)         台词)          叙事)           配音词)
```

### 解耦后的目录结构

```
creative-core/                    # 共享核心库（新仓库 or monorepo core/）
  style/
    vector.py                     # StyleVector dataclass + 坐标运算
    presets.py                    # 预设管理（加载/保存/合并/覆盖）
    render.py                     # 坐标 → 文本指令的通用渲染框架
    aesthetic.py                  # 审美概念（风骨/文气/分寸/意在言外）
  knowledge/
    client.py                     # cocobook MCP client
    search.py                     # 全文 + 语义搜索封装
  llm/
    router.py                     # 多模型路由 + fallback + token 管理
    call.py                       # 统一调用接口（兼容 Anthropic/OpenAI/z.ai）
  quality/
    base.py                       # 评分框架（维度注册 + 加权计算 + 硬门控）
    patterns.py                   # AI 模式检测（通用部分，模型无关）

article-pipeline/                 # 文章管线（依赖 creative-core）
  style_adapter.py                # 品类预设 + injection level + genre_rules
  synthesis.py                    # 多源对比 → 结构化判断
  framework.py                    # 论证方法论（品类专属）
  prosody.py                      # 语感范本选择 + few-shot 注入
  ...（现有 research/outline/writer/review/publish）

screenplay-pipeline/              # 未来：剧本管线
  style_adapter.py                # 角色声音坐标 + 场景氛围坐标
  synthesis.py                    # 冲突提取 + 动机分析
  framework.py                    # 节拍表 + 三幕/五幕/序列八
  ...

novel-pipeline/                   # 未来：小说管线
  style_adapter.py                # 叙述者坐标 + POV 控制
  synthesis.py                    # 世界观一致性 + 人物弧光
  framework.py                    # 情节结构（英雄之旅/多线交织/...）
  ...
```

### 5 维坐标在不同格式中的语义映射

| 维度 | 文章 | 剧本 | 小说 | 短视频脚本 |
|------|------|------|------|-----------|
| warmth | 对读者的距离感 | 角色间的情感温度 | 叙述者对人物的态度 | 与观众的亲密度 |
| edge | 判断的确定性 | 冲突的尖锐程度 | 叙述者的立场强度 | 观点的冲击力 |
| energy | 信息推进节奏 | 场景节拍密度 | 情节推进速度 | 剪辑节奏感 |
| register | 用词正式度 | 角色社会阶层标记 | 叙述语体 | 口语/书面 |
| density | 信息压缩程度 | 台词的留白 vs 直说 | 描写密度 | 信息量/秒 |

每种格式需要一个 `style_adapter.py` 把通用坐标翻译成格式专属的 prompt 指令。坐标值相同，但渲染出的指令文本完全不同。

### 单管线 vs 多管线：结论

**独立管线 + 共享核心库。**

Studio（prompts 项目）已经验证了这个模式：5 条管线（Image/VI Discovery/Layout/Video/3D），各自独立，共享术语系统 + 品牌系统 + 质量门控 + 生成 API 层。

不做"万能管线 + format 参数"的原因：

1. **抽象泄漏** — 文章的 review 检查事实+AI句式，剧本的 review 检查节拍推进+角色声音区分。强行统一接口两边都别扭
2. **演进速度不同** — article-pipeline v0.3，剧本管线从零开始。耦合在一起互相拖累
3. **synthesis/framework/prosody 实现完全不同** — 共享接口名但实现 100% 不同，不如各自独立
4. **Studio 实证** — Image 管线的 compose 和 Video 管线的 compose 完全是两个东西，强行统一会制造更多抽象层

### 解耦实施路径

**Phase 1（本月）**: 不动现有代码结构，但在设计新模块（synthesis/framework/prosody）时，接口设计为可独立于 article-pipeline 的形态。

**Phase 2（月 2-3）**: 提取 `creative-core` 库：
- `style.py` 拆分为 `creative-core/style/` + `article-pipeline/style_adapter.py`
- LLM 调用层抽象（当前硬编码在 writer.py）
- cocobook client 独立（当前硬编码在 research.py）

**Phase 3（月 4+）**: 第二条管线（Linux/DevOps 文章 或 短视频脚本）基于 creative-core 构建，验证解耦是否干净。

### Studio 可复用模式对照

| Studio 模式 | 文章管线对应 | 当前状态 |
|------------|-------------|---------|
| 术语系统（59 域 15K 词） | cocobook 标注 + 知识索引 | 已有，用法错误（当搜索引擎而非理解基础） |
| compose 管线（brief→compose→generate→adapt） | research→synthesis→outline→write | 缺 synthesis 层 |
| Production Profile vs Brand Guidelines | 管线执行逻辑 vs 风格系统 | 耦合在 style.py，需解耦 |
| quality_regression 回归测试 | review 10 维评分 | 已有，缺正向质量信号（D1） |
| 品牌 negative constraints（banned 列表） | AI 句式禁止列表 | 实施中（S4） |
| few-shot 锚定（reference-prompts） | writing_craft 范本 | 已有，用法错误（当语感范本而非方法论来源） |
| 多模型路由（按任务类型选模型） | 多 endpoint fallback | 有基础版，缺任务级路由 |
| 10 条 AI 原生设计原则 | 无 | 需建立（写作领域的等价物） |

### Studio 深层架构模式（调研补充 2026-07-01）

Studio 的 prompts 系统本质是一个**编译器**，不是模板库。以下模式直接适用于 creative-core 设计：

#### 模式 1: Cascade Compiler（级联编译）

Studio 明确测试并否决了"一个大 prompt"方案。实际使用 5 层级联：

```
intent → modality → category → product → scenario → validated vocabulary
```

每层过滤，validated vocabulary（领域术语）最后才注入。这对 article-pipeline 的启示：

```
当前（一步到位）:
  research_note + style_block + genre_rules → writer prompt（一坨）

应该（级联编译）:
  layer 1: synthesis 输出（核心判断 + 证据结构）
  layer 2: framework 选择（论证方法 + 组织骨架）
  layer 3: style 渲染（5 维坐标 → 格式专属指令）
  layer 4: prosody 注入（语感范本 + negative constraints）
  layer 5: validated material（cocobook 精选素材，最后注入）
```

每层独立可测试、可替换、可跳过。

#### 模式 2: Pluggable Knowledge Domains（可插拔知识域）

每个领域 = 一个目录 + 固定 5 文件契约：

```
data/domains/<domain>/
  manifest.yaml          # 域元信息（名称、描述、版本、依赖）
  processes.yaml         # 该域的工序/流程定义
  school_routing.yaml    # 风格流派路由
  vocabulary.json        # 术语表
  vocabulary_tags.json   # 术语分类标签
```

加新领域 = 放一个新目录，不改引擎代码。

对 article-pipeline 的启示：当前 category（21 种品类）的定义散落在 style.py/_PRESETS + writer.py/_genre_rules + outline.py/OUTLINE_PROMPT 三处。应该每个品类一个目录：

```
genres/tutorial/
  manifest.yaml          # 品类元信息
  framework.yaml         # 该品类的方法论框架
  style_preset.yaml      # 风格预设值
  genre_rules.yaml       # 硬性写作规则
  prosody_samples/       # 语感范本（few-shot 用）
```

加新品类 = 放一个新目录。不改管线代码。

#### 模式 3: Typed JSON Contracts（类型化阶段契约）

阶段间传递结构化数据，不是自由文本。有 validate_contracts.py 校验。

对 article-pipeline 的启示：当前 research → writer 传递的是自由格式的 research_note（纯文本拼接）。应该定义契约：

```python
# research → synthesis 契约
ResearchOutput = {
    "sources": [...],          # 来源列表（带类型标记）
    "claims": [...],           # 提取的 claim 列表
    "data_points": [...],      # 量化数据
    "conflicts": [...],        # 已发现的来源间矛盾
}

# synthesis → outline 契约
SynthesisOutput = {
    "core_judgment": str,      # 一句话核心判断
    "evidence_for": [...],     # 支持证据
    "evidence_against": [...], # 反面证据
    "resolution": str,         # 分歧解决方案
    "unique_angle": str,       # 独特角度
    "differentiation": str,    # 与搜索结果的差异
}

# outline → writer 契约
OutlineOutput = {
    "framework": str,          # 使用的方法论框架名
    "structure": [...],        # 段落骨架
    "takeaway": str,           # 一句话卖点
    "prosody_samples": [...],  # 选定的语感范本
    "negative_constraints": [...],  # 禁止项
}
```

#### 模式 4: 风格作为结构化数据

Studio 的品牌不是散文描述，是 purpose / require / allow / avoid 四字段结构：

```yaml
# Studio 的做法（art-directions.yaml）
wenpai:
  visual_roles:
    blog_header:
      purpose: "品牌博客配图"
      require: ["blue-white gradient", "editorial layout"]
      allow: ["subtle texture", "light typography"]
      avoid: ["3D blocks", "landscape", "ink painting"]
```

对风格系统的启示：当前 style 渲染输出是散文指令。改为结构化后：

```yaml
# 文章品类风格（结构化版）
tutorial:
  purpose: "让新手建立心理模型后能独立操作"
  require: ["认知脚手架", "每步验证点", "终态展示"]
  allow: ["类比", "假设场景", "口语化过渡"]
  avoid: ["抽象理论先行", "无验证的步骤列表", "上来就操作无全貌"]
  aesthetic: ["分寸"]
  prosody: "short-push"  # 短句推进型
```

机器可检查（review 时验证 require 是否满足、avoid 是否出现），不依赖 LLM 判断。

#### 模式 5: Quality Gate 知道自己的边界

Studio 的 concept-density 模块：当检测到概念密度低于阈值时，不强行文本生成，而是自动升级到 reference-image 锚定。系统声明"这个我做不好，需要换方式"。

对 article-pipeline 的启示：
- research 素材不足时，不强行写 → 自动标记为"素材不足，需补充"
- synthesis 无法形成判断时（来源全部一致，无矛盾无独特性）→ 标记为"选题无差异化空间"
- writer 产出 ai_check < 4.0 → 不走 revise，标记为"prompt 约束失效，回溯诊断"

系统应该知道自己什么时候不行，避免硬着头皮产出垃圾。

---

## 方法论层的具体构成

### 什么是"写作方法论"

方法论回答的问题是：**面对这类话题和这类读者，怎么思考和组织才有说服力。**

它与格式（H2/H3）、风格（冷暖/锐钝）、语感（长短句交替）不同，是思维方式。

### 五个核心品类的方法论框架（Phase 1 硬编码）

#### tutorial（教程）— 认知脚手架法

```
方法: 先给全貌建心理模型，再拆步骤，每步说清楚"为什么这一步在这里"
原理: 人在没有全貌时学步骤 = 记忆负担（工作记忆 7±2 限制）
结构:
  1. 终态展示（"做完后你会得到什么"）
  2. 心理模型（"整体分几部分，它们什么关系"）
  3. 逐步骤执行（每步：做什么 + 为什么 + 验证点）
  4. 常见岔路（"如果你看到 X 错误，说明..."）
反模式: 上来就"第一步打开终端"（读者不知道要去哪里）
```

#### comparison（对比）— 维度统一法

```
方法: 先统一评估维度和定义，再逐维度对比，最后给决策树
原理: 无维度的对比 = "各有优劣"废话；有维度的对比 = 可操作的选择指南
结构:
  1. 明确评估场景（"在什么条件下比？"）
  2. 定义维度 + 每个维度的评判标准
  3. 逐维度打分（带证据）
  4. 决策树（"如果你是 X 情况 → 选 A；如果 Y → 选 B"）
反模式: "A 有这些优点，B 有那些优点，请根据需要选择"（等于没说）
```

#### opinion（观点）— Steel-man 反驳法

```
方法: 先给出对方最强版本的论证（steel-man），再找到其隐含假设，翻转这个假设
原理: 直接攻击弱版对手 = straw-man，读者不信。攻击最强版本 = 说服力
结构:
  1. 主流观点是什么（steel-man 版：最善意、最强的表述）
  2. 它的隐含假设是什么（"这个观点成立的前提是..."）
  3. 这个假设在什么条件下不成立（我们的证据）
  4. 翻转后的新观点 + 它的适用边界
反模式: "很多人认为 X，但我认为 Y"（无论证过程，纯断言）
```

#### troubleshooting（故障排查）— 诊断树法

```
方法: 从症状分类开始，用排除法缩小范围，定位根因，给出解决+预防
原理: "试试 A，不行试 B"是赌博不是排查。诊断树让读者理解为什么
结构:
  1. 症状描述 + 分类（"如果你看到 X → 可能是 A/B/C 类问题"）
  2. 快速分类检查（"运行这个命令，看输出是 P 还是 Q"）
  3. 各分支的根因分析 + 修复
  4. 预防措施（"下次避免这个问题的配置/习惯"）
反模式: "解决方案：1. 重启 2. 清缓存 3. 重装"（碰运气列表）
```

#### case-study（案例研究）— 经验萃取法

```
方法: 不只是"我做了什么"，而是"什么条件 + 什么决策 + 什么结果 + 可迁移规律"
原理: 纯叙事无法迁移；规律提取后读者可以判断自己是否适用
结构:
  1. 初始条件（"我们的情况：规模/约束/目标"）
  2. 关键决策点（"在 X 时，我们选了 A 而不是 B，因为..."）
  3. 结果 + 数据（"效果：指标从 X 变成 Y"）
  4. 可迁移规律（"如果你也满足条件 Z，这个方法大概率适用"）
  5. 不可迁移的部分（"我们的情况特殊在..."）
反模式: "我们成功了！你也可以！"（幸存者偏差，不说限制条件）
```

### 方法论来源

- cocobook `chinese-writing` topic 中的写作方法类书籍
- 麦基《故事》— 冲突/节拍/场景转折（剧本管线 framework）
- 坎贝尔《千面英雄》— 叙事结构（小说管线 framework）
- 芝加哥大学《论证的技艺》— 论证结构（opinion/editorial）
- 威廉斯《风格的要素》— 句子力学（prosody 层）

### cocobook 写作类书籍的正确用法

当前：`writing_craft` 搜出段落 → 当"语感范本"喂给 writer → 模仿句式
正确：

| 用途 | 提取什么 | 服务哪层 |
|------|---------|---------|
| 方法论 | "教程要先给全貌" / "论证要 steel-man" | framework 层 |
| 结构范本 | 一篇好文章的骨架长什么样 | outline 层 |
| 语感范本 | 句式节奏、段落呼吸的具体段落 | prosody 层（给 writer few-shot） |

同一本写作书的不同章节可能服务不同层。不能一股脑当"范本"用。

---

## 工程与创作的张力（Engineering vs Creation）

### 问题本质

文章管线是工程系统还是创作工具？两者的控制逻辑相反：

| | 工程思维 | 创作思维 |
|---|---|---|
| 目标 | 可预测、可复现 | 意外之喜、不可复现 |
| 约束 | 越硬越好（规则明确） | 越软越好（允许偏离） |
| 质量 | 底线达标 = 合格 | 底线之上还有天花板 |
| 错误 | 必须消除 | 某些"错误"反而有趣 |
| 优化 | 减少方差 | 保留方差中的好部分 |

管线不能只选一边。纯工程 = 高级模板机（3→7 容易，7→9 不可能）。纯创作 = 不可控（有时 9 分有时 3 分）。

### 解法：双轨约束模型

```
硬约束（工程层）— 保底线，不可违反
  │
  │  效果：把 3 分拉到 7 分
  │  机制：规则检查 + 自动拦截
  │  举例：
  │    - 禁止特定 AI 句式（_NEGATIVE_CONSTRAINTS）
  │    - 素材密度不足不进入写作（synthesis 门控）
  │    - value_density < 4.0 不发布
  │    - differentiation 字段不能为空
  │    - 每段必须有信息增量（不能空转）
  │
  ▼
软约束（创作层）— 提上限，允许有理由地偏离
    效果：从 7 分到 9 分的可能性
    机制：advisory 评分 + 人工复核
    举例：
      - 语感范本（prosody samples）— 提供方向不强制
      - 审美概念（"意在言外"）— 激活而非命令
      - framework 建议的段落结构 — 可打破但需要理由
      - 风格坐标的微调 — ±0.2 以内的偏离不扣分
```

### 工程层设计原则

1. **可验证性**：每条硬约束必须有自动化检测方法（不能靠人读才能判断）
2. **最小化**：硬约束越少越好，只管"绝对不能犯的错"
3. **负面定义**：说"不能做什么"比"必须做什么"更适合工程层（创作有无限种正确方式，但错误模式有限）
4. **分层拦截**：越早拦截越便宜（synthesis 层拦截 > outline 层拦截 > write 后打回）

### 创作层设计原则

1. **非强制性**：软约束是"参考方向"不是"必须遵守"
2. **范本驱动**：好的范本比好的规则更能引导创作（few-shot > instruction）
3. **允许意外**：审美概念激活 LLM 的联想空间，结果不完全可预测，这是特性不是 bug
4. **人工最终判断**：7→9 的差距只有人能判断，系统只负责创造条件

### 在级联编译中的体现

```
Layer 1 SYNTHESIS:  纯工程层（结构化输出，门控拦截）
Layer 2 FRAMEWORK:  工程为主 + 轻创作（方法论是工程，段落分配允许偏离）
Layer 3 STYLE:      工程层（结构化约束编译，纯配置）
Layer 4 PROSODY:    纯创作层（范本引导，允许偏离，不做强制检查）
Layer 5 COMPILE:    工程层（组装，token 控制）+ 创作自由度在 writer prompt 内部
```

核心洞察：前 3 层是工程（确定性、可回滚、可检查），第 4 层是创作（范本引导、允许意外），第 5 层是混合（工程的组装 + 创作的生成）。

### 实际影响

这个模型决定了哪些环节投入自动化、哪些环节保留人工：

| 环节 | 性质 | 自动化程度 |
|------|------|-----------|
| 选题评估 | 工程 | 全自动（密度/饱和度/差异化三指标） |
| synthesis 生成 | 工程 | 全自动 + confidence 门控 |
| framework 选择 | 工程 | 全自动（品类 manifest 映射） |
| 段落结构 | 工程为主 | 自动生成，允许人工调整 |
| 风格编译 | 工程 | 全自动（坐标→约束的确定性映射） |
| 语感注入 | 创作 | 范本推荐自动，效果判断人工 |
| 写作生成 | 混合 | 自动生成，质量判断双轨 |
| 质量检查 | 工程部分全自动 | 硬约束自动拦截；软约束 advisory 展示 |
| 发布决策 | 创作 | 系统建议，人工最终决定 |

### 与成本的关系

用户明确：多 LLM 供应商可选（DeepSeek 等），成本不是约束。这意味着：

- synthesis 层可以用便宜模型（GLM/DeepSeek）跑多次取最佳
- 不需要因为成本牺牲任何质量层的调用
- 可以做"写 3 篇选最好的 1 篇"策略（创作层的方差利用）
- framework 和 prosody 的 LLM 辅助选择不需要吝啬 token

这解放了架构：不需要把所有逻辑塞进一次 LLM 调用里"省钱"，可以按级联模型老老实实走 5 层。

---

## 素材策略：从文字到视觉的编译延伸

### 背景

文章不只是文字。配图质量直接影响传播力和阅读完成率。当前管线只产出文本，视觉素材完全依赖人工。

两个参考项目揭示了 AI 素材生成的两种范式：

### 参考项目分析

#### archify（架构图 Skill）

| 维度 | 分析 |
|------|------|
| 定位 | 纯工程产物——系统架构/流程/序列/数据流/生命周期图 |
| 输入 | 自然语言描述或 Mermaid 代码 |
| 输出 | 自包含 HTML（SVG + 主题切换 + 导出菜单） |
| 核心模式 | 5 种图类型 × 结构化 JSON schema × 渲染器验证 |
| prompt 工程 | 不做自由生成，强制结构化中间产物（JSON）→ 确定性渲染 |
| 质量保证 | schema 验证 + 布局碰撞检测 + CJK 文本宽度感知 |
| 适用场景 | 技术文章的架构说明图、流程解释图 |

关键借鉴：**结构化中间产物 + 确定性渲染** = 可控的视觉输出。让 LLM 描述图的结构，再用渲染器保证视觉质量。

#### ian-xiaohei-scenes（小黑实物场景图 Skill）

| 维度 | 分析 |
|------|------|
| 定位 | 创作产物——文章正文配图的视觉语言系统 |
| 输入 | 中文文章内容 + 用户处境分析 |
| 输出 | 16:9 正文配图 或 超横版长卷故事图 |
| 核心模式 | 母版锚定 + 变异规则 + 物件隐喻映射 |
| prompt 工程 | 先"消化内容提炼处境"→ shot list → 母版锁定 → 逐张生成 |
| 质量保证 | 母版作为质量标尺 + 硬性预算（1个动作/1个主物件/最多4标签）+ QA checklist |
| 适用场景 | 打工人共鸣图、项目复盘、AI 时代处境、观点隐喻 |

关键借鉴：

1. **先理解再出图**（消化内容 → 提炼处境 → 物件隐喻映射），和我们 synthesis 层的思路一致
2. **母版锚定 + 强制变异**，不自由发挥，有质量标尺，但必须偏离防止雷同
3. **硬性预算**，创作层也需要工程约束（和双轨模型一致）
4. **事实锚定**，只使用用户提供的事实，不编造（和我们 trust tier 思路一致）
5. **标准模式 vs 彩蛋模式**，同一套视觉语言支持日常和特殊场景

### 素材在管线中的位置

```
Level 1: 文字编译（当前管线，独立完整）
  keyword → synthesis → framework → style → prosody → compile → article

Level 2: 视觉编译（与 Studio 协作）
  article.visual_brief → Studio pipeline → 配图资产 → 组装发布

Level 3: 素材自给（本地能力，不依赖 Studio）
  article.key_concepts → archify（技术图）→ inline figures
  article.narrative_points → xiaohei-scenes（共鸣图）→ hero/inline images
```

三个 Level 不互斥：
- Level 1 是基础，任何时候都能独立产出纯文本文章
- Level 2 是高配，品牌内容套件走 Studio 协作
- Level 3 是中配，日常文章用本地 Skill 快速出图

### 素材类型与工具映射

| 文章类型 | 需要的配图 | 工具 | 触发条件 |
|---------|-----------|------|---------|
| 技术教程 | 架构图、流程图、数据流图 | archify | framework 含多组件交互 |
| 观点文 | 观点隐喻图、处境共鸣图 | xiaohei-scenes | 有明确立场/处境描述 |
| 对比评测 | 对比表格图、性能曲线 | archify(dataflow) | 多维度对比数据 |
| 项目复盘 | 长卷故事图、时间线 | xiaohei-scenes(彩蛋) | 有时间跨度的叙事 |
| 故障排查 | 序列图、调用链 | archify(sequence) | 多步排查过程 |
| 品牌营销 | 定制品牌配图 | Studio 协作 | brand trust_tier |

### 集成方案（Phase 5 预留）

不在当前改造范围内做，但架构设计上预留接口：

```python
@dataclass
class VisualBrief:
    """Level 2/3 视觉编译的输入契约"""
    article_id: str
    title: str
    key_concepts: list[str]       # 核心概念（archify 输入）
    narrative_points: list[str]   # 叙事节点（xiaohei-scenes 输入）
    mood: str                     # 从 style 坐标推导
    genre: str                    # 决定默认配图类型
    figures_needed: list[dict]    # [{position: "hero"|"inline", type: "diagram"|"scene"}]
```

FrameworkOutput 新增可选字段（Phase 5 时激活）：

```python
@dataclass
class FrameworkOutput:
    # ... 现有字段 ...
    visual_anchors: list[dict] | None = None  # [{section_role, concept, suggested_visual_type}]
```

### 与 Studio 的分工

| | elementary 本地 | Studio 协作 |
|---|---|---|
| 触发 | 自动（genre 匹配） | NATS 请求 |
| 速度 | 即时（Skill 调用） | 异步（分钟级） |
| 质量 | 中等（Skill 标准） | 高（品牌定制） |
| 适用 | 日常文章、技术教程 | 品牌内容、重点推广 |
| 成本 | LLM 调用费 | LLM + Studio 工作量 |

日常文章默认走 Level 3（本地 Skill），重要内容升级到 Level 2（Studio）。决策标准：trust_tier = EXTERNAL 或 priority >= 2 → Studio；否则本地。

### 已确认的基础设施

| 能力 | 状态 | 位置 |
|------|------|------|
| archify Node.js 渲染器 | 可直接部署 | elementary (Node v22.23.0) |
| 图像生成后端 | 3 后端就绪 | Studio: Lovart SDK(56模型) + OpenAI(gpt-image-2) + Gemini |
| prompt 编译系统 | 成熟 | Studio prompts workspace（59域/15K术语/意图→英文prompt） |
| 截图服务 | 就绪 | elementary Pinchtab (headless Chrome, port 9867) |
| 图片优化链 | 就绪 | elementary (pngquant/oxipng/jpegoptim/cwebp/svgo) |
| 品牌配图 | 可用 | Studio image-gen workspace → NATS 交付 |

### 四类素材的生产路径

```
1. 架构/流程/技术图（确定性产物）
   article → VisualBrief.key_concepts → archify JSON → render-*.mjs → HTML/SVG/PNG
   执行者: elementary 本地（Node.js 直跑）
   质量: schema 验证 + 布局碰撞检测（工程层，确定性高）

2. 内容配图/共鸣图（创作性产物）
   article → VisualBrief.narrative_points → Studio prompts compose → image-gen → PNG
   执行者: Studio（elementary NATS 发 visual_brief → Studio 出图 → 回传资产路径）
   质量: Studio quality_gate (score >= 0.6) + 人工验收
   参考: xiaohei-scenes 的"先理解处境再出图"模式可集成到 prompts compose 流程

3. 产品截图（实测证据）
   article.verifiable_operations → Pinchtab 截图 → img-process 优化 → inline figure
   执行者: elementary 本地（Pinchtab headless Chrome）
   质量: 自动裁切 + 优化压缩，无需 AI
   场景: 教程步骤验证、对比评测实测、故障排查实际报错

4. 数据可视化（统计图表）
   article.data_points → gnuplot/matplotlib → SVG/PNG
   执行者: elementary 本地
   质量: 数据准确性（硬约束）
   场景: 性能对比、趋势分析、基准测试结果
```

### 截图在管线中的特殊地位

截图不是"配图"而是**证据**。在我们的反 slop 策略中：

- "可验证操作"是 value_density 的核心维度（>30% 段落需含具体操作）
- 截图是操作可验证性的最高级证明，比代码块更直观
- 教程类文章的截图不可省略：读者需要看到"做对了长这样"

截图策略：

| 时机 | 截图类型 | 触发 |
|------|---------|------|
| 步骤验证 | 操作结果截图 | framework.structure 中 role=steps 的段落 |
| 终态展示 | 完成后效果截图 | framework.structure 中 role=opening 的"展示终态" |
| 错误示例 | 错误信息截图 | framework.structure 中 role=detours |
| 对比展示 | 前后对比截图 | genre=comparison 的维度对比段落 |

在 FrameworkOutput 中，visual_anchors 应区分"需要截图"和"需要生成图"：

```python
visual_anchors: list[dict] | None = None
# [{
#   section_role: str,
#   concept: str,
#   visual_type: "screenshot" | "diagram" | "scene" | "chart",
#   screenshot_target: str | None,  # Pinchtab URL（visual_type=screenshot 时）
#   diagram_spec: str | None,       # archify 自然语言描述（visual_type=diagram 时）
# }]
```

### 已决策

1. **xiaohei-scenes 风格 → Studio prompts 新 domain**。复用 Studio 已有的意图编译+术语注入+质量门禁能力，不在 elementary 本地重建图像生成链路。elementary 只负责发 visual_brief，Studio 负责从意图到出图的全流程。
2. **截图先标记位置，后续自动化**。当前 FrameworkOutput.visual_anchors 标记"这里需要截图"即可，人工用 Pinchtab 补充。后续可能接入质检管线（play-smoke/Playwright）实现自动截取，到时评估是新建截图管线还是复用现有 QA 工具链。
3. **配图位置在 outline 阶段确定**。与 framework 绑定：framework.structure 中每个段落 role 可声明 visual_type 需求，outline 生成时同步输出 visual_anchors。不在 compile 阶段临时决定。

---

## 总结：系统需要什么

```
已有（能力在，用法需调整）：
  - cocobook 知识库（9270 册，32K+ 标注）→ 应作为 synthesis 的理解基础
  - 风格系统（5 维坐标）→ 应解耦为通用创作人格层
  - review 模块（10 维评分）→ 应加正向质量信号
  - writing_craft 范本 → 应按层分类使用（方法论/结构/语感）
  - archify 渲染器（本地 Node.js）→ 技术图确定性生成
  - Pinchtab + headless Chrome → 截图作为证据
  - Studio 图像生成能力（3 后端）→ 创作性配图

缺失（需新建）：
  - synthesis 模块 — 从碎片形成结构化理解
  - framework 模块 — 品类专属的组织方法论
  - prosody 模块 — 独立于风格的语感控制
  - style_adapter — 风格坐标到格式专属指令的翻译层
  - creative-core 共享库 — 风格/知识/LLM/质量的通用层
  - visual.py — 素材请求编排（VisualBrief → archify/Studio/Pinchtab）
  - compile 结构化输出 — JSON 元数据（SEO/visual_anchors/tags）

架构模型：
  - 级联编译 5 层（synthesis → framework → style → prosody → compile）
  - 双轨约束：硬约束（工程层，保底线 3→7）+ 软约束（创作层，提上限 7→9）
  - 可插拔品类域（21 品类 × 5 文件契约，新增品类 = 放目录不改代码）
  - 多 LLM 供应商（DeepSeek/GLM/Claude），成本不是约束

素材策略：
  - 技术图（archify，工程/确定性/本地）
  - 内容配图（Studio prompts + image-gen，创作/异步）
  - 截图证据（Pinchtab，工程/本地）
  - 数据图表（gnuplot/matplotlib，工程/本地）
  - xiaohei-scenes → Studio prompts 新 domain

方向（长期）：
  - 独立管线 + 共享核心库（Studio 已验证的模式）
  - 文章管线是第一个，验证核心库接口后横向复制
  - 每种格式的 synthesis/framework/prosody 各自独立实现
```
