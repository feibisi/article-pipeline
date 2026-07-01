# DBSkill 集成报告

> 更新: 2026-07-01 | 来源: dontbesilent/dbskill | 集成者: elementary VM

本文档记录 dontbesilent/dbskill 商业工具箱与 article-pipeline 的集成情况。

## 概述

dbskill 是一个 24-agent 技能工具箱，源自 12,307 条推文的知识提取。本次集成了其中 3 个核心技能到 article-pipeline 的 review 层。

## 已集成模块

### P0: dbs-ai-check — AI 指纹检测

**文件**: `article_pipeline/review/dbs_ai_check.py`

**功能**: 检测文稿中的 22 种 AI 写作特征

**检测维度**:
- 强信号 (8 个): 堵住反驳, 匀速排比, 让步模板, 命名仪式, 不是X是Y, 开头三件套, 连接词过度, 翻译腔
- 中信号 (8 个): 机械列举, 套话连接, 意思就是, 缺乏叙事, 概念轰炸, 观点堆叠, 硬造结构, 硬造问题
- 弱信号 (6 个): 避免主观, 过度解释, 常见类比, 常见谚语, 热词堆叠, 意译式改写

**集成点**: `review/__init__.py` 的 `run_self_review()`
- 权重: 15%
- 软阈值: 4.0

**示例用法**:
```python
from article_pipeline.review.dbs_ai_check import DbsAIChecker

checker = DbsAIChecker()
result = checker.check_all("你的文稿内容...")
report = checker.generate_report(result)
```

### P1: dbs-benchmark — 选题五重过滤

**文件**: `article_pipeline/topic_filter.py`

**功能**: 5 个筛子评估选题价值

**五重过滤**:
1. 有人搜吗 — 搜索结果数量和质量检测
2. 有痛点吗 — 问题/错误/故障关键词检测
3. 有素材吗 — 教程/文档/案例/问答素材检测
4. 你能写吗 — 选题范围检测（过宽/过深）
5. 值得写吗 — 同质化检测 + 差异化空间

**通过标准**: 至少通过 4 个筛子

**示例用法**:
```python
from article_pipeline.topic_filter import BenchmarkTopicFilter

bf = BenchmarkTopicFilter(search_results=[...])
result = bf.filter_topic("Nginx 缓存配置错误修复")
print(result.score, result.passed)
```

### P2: dbs-resonate — 文稿共鸣诊断

**文件**: `article_pipeline/review/dbs_resonate.py`

**功能**: 5 维传播心理学检测文稿共鸣潜力

**五维度**（基于传播学经典理论）:
1. 沉默解除（沉默的螺旋，诺依曼 1974）— 是否说出受众憋着不敢说的话
2. 满足动机（使用与满足理论，卡茨 1959）— 满足什么心理需求
3. 立场框架（框架理论，恩特曼 1993）— 站在谁那边
4. 传播入口（两级传播理论，拉扎斯菲尔德 1944）— 谁会第一个传播
5. 信念结构（认知一致性理论，费斯廷格 1957）— 确认什么信念，触发行动冲动

**评分标准**:
- 有效维度 >= 3 → 8-10 分
- 有效维度 >= 2 且无无效 → 6-7 分
- 有效维度 >= 1 且无效 <= 2 → 4-5 分
- 否则 → 0-3 分

**示例用法**:
```python
from article_pipeline.review.dbs_resonate import ResonanceChecker

checker = ResonanceChecker()
result = checker.check_draft("你的文稿内容...")
print(result.overall_score, result.status)
```

## 未集成模块（待评估）

以下 dbskill 模块可能对 article-pipeline 有价值，尚未评估：

| 模块 | 功能 | 可能用途 |
|------|------|----------|
| dbs-deconstruct | 概念拆解 | research 阶段深化理解 |
| dbs-content | 内容质量检测 | review 层补充维度 |
| dbs-hook | 标题钩子 | outline 阶段优化开头 |
| dbs-slowisfast | 慢即是快（深度分析） | 研究素材质量评估 |
| dbs-spread | 传播心理解码 | published 内容分析 |

## 设计原则

1. **启发式为主**: 所有检测基于关键词和模式匹配，不依赖外部 API
2. **可配置性**: 所有阈值和关键词列表可调整
3. **独立运行**: 每个模块可独立使用，不强制绑定到 pipeline
4. **报告优先**: 提供可读性强的 Markdown 报告，便于人工审查

## 测试

每个模块包含内置测试用例：

```bash
# 测试 AI 检测
python3 -m article_pipeline.review.dbs_ai_check

# 测试选题过滤
python3 -m article_pipeline.topic_filter

# 测试共鸣诊断
python3 -m article_pipeline.review.dbs_resonate
```

## 依赖

无新增外部依赖。所有模块使用 Python 标准库和已有依赖。

## 下一步

1. 将 dbs-benchmark 集成到 `article-pipeline add` 命令
2. 将 dbs-resonate 集成到 review_server UI
3. 评估更多 dbskill 模块的集成价值

## 参考资料

- dbskill 仓库: https://github.com/dontbesilent2025/dbskill
- 24-agent 技能列表: `/tmp/dbskill/skills/`
- 传播心理学理论: dbs-resonate SKILL.md
