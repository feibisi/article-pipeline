# Article Pipeline — 系统定义

> 版本: 0.3.0 | 更新: 2026-07-01 | 维护: elementary VM

## 这是什么

Article Pipeline 是一套 AI 原生的中文技术内容生产系统。从关键词到 WordPress 发布，全链路自动化，人类只在关键决策点介入。

## 设计哲学

**AI 原生优先** — 不是"人写文章 + AI 辅助"，是"AI 写文章 + 人做质控"。系统设计围绕 LLM 的能力边界展开：在 LLM 擅长的地方（结构化写作、格式遵循、大量素材整合）放手让它做；在 LLM 不可靠的地方（事实准确性、编造倾向、风格微调）用规则和检查兜底。

**三层控制模型**:

```
事实层 (Trust Tier)     → 能不能写：信息来源边界
风格层 (Style System)   → 怎么写：语气、节奏、立场强度
质量层 (Review Module)  → 写得好不好：AI 检测、编造检查、术语规范
```

三层正交，互不干涉。Tier 不管你写得好不好看，Style 不管事实对不对，Review 事后评估所有维度。

## 核心假设

1. **LLM 会编造** — 不是偶尔，是必然。所有事实必须有参考素材支撑，没有素材宁可留空。
2. **LLM 能遵循结构指令** — 给定明确的段落骨架和写作规则，LLM 能按要求输出。
3. **LLM 对风格微调不敏感** — 从"冷"到"暖"能感知到区别，但 +0.3 到 +0.6 的区别 LLM 基本无感。风格系统的精度为人类编辑服务，不为 LLM 服务。
4. **审查可自动化** — 大部分质量问题可以用模式匹配 + 语义搜索发现，不需要人逐字审。

## 系统边界

**做什么**:
- 技术教程、产品评测、行业观点、品牌营销、新闻通知等 21 种品类的中文文章
- WordPress 平台发布（Gutenberg 区块格式）
- 自动化研究、大纲、写作、审查、发布全流程

**不做什么**:
- 小说/剧本/诗歌等创意写作（需独立 workspace）
- 视频脚本（归 studio VM 的 content-factory）
- 翻译（归 translate VM 的 wptea 管线）
- 实时新闻（无法验证时效性事实）

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| 语言 | Python 3.11+ | 纯 Python，无框架依赖 |
| LLM | GLM-5.1 via z.ai API | Anthropic-compatible endpoint，DeepSeek 备选 |
| 知识库 | cocobook MCP (huawei-pc:8087) | 全文检索 + 语义搜索 |
| 任务队列 | SQLite | 本地轻量，单 VM 运行 |
| 发布 | WordPress REST API | Gutenberg 区块格式 |
| 审查 UI | review_server.py (localhost:8765) | 内置 Web UI |

## 模块关系

```
┌─────────────────────────────────────────────────────────────────┐
│                        Pipeline Orchestrator                     │
├────────┬──────────┬──────────┬──────────────┬──────────────────┤
│Research│  Outline │  Writer  │    Review    │    Publish        │
│        │          │          │              │                   │
│cocobook│ GLM-5.1  │ GLM-5.1  │ Pattern Match│ WP REST API       │
│DDG web │ Ollama   │ (render_ │ Semantic     │ Gutenberg blocks  │
│code    │ fallback │  style_  │ cocobook     │ translate bridge  │
│VM peer │          │  block)  │ Humanizer-zh │                   │
├────────┴──────────┴──────────┴──────────────┴──────────────────┤
│ Config │ DB (SQLite) │ Style System │ Trust Tier │ Text Utils   │
└─────────────────────────────────────────────────────────────────┘
```

## 数据流

```
1. add(keyword, category, platform, priority)
   → DB: status=queued

2. research(task_id)
   → cocobook 全文检索 + DDG 搜索 + 内容农场过滤 + AI 套话检测
   → DB: status=researching → research_note saved

3. outline(task_id)
   → claim/audience/hook 生成 + 段落结构
   → [TIER_EXTERNAL: human gate → status=outline_review → 等待人工确认]
   → DB: status=outlining → outline saved

4. write(task_id)
   → Trust Tier 规则 + Style 指令 + Genre 规则 + 素材 → LLM 生成
   → DB: status=writing → article saved

5. review(task_id)
   → 10 维评分 + overall_score + suggestions
   → DB: status=reviewing → review results saved
   → [score < 30/50: hard reject]

6. (human review via review_server)
   → approve → publish | request revision → rewrite → re-review

7. publish(task_id)
   → WordPress REST API → DB: status=done
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

## 质量标准

### 硬门控（不通过则不发布）

- Humanizer 总分 < 30/50
- 编造检查 fabrication_flags > 2
- "不是...而是..." 模板句超频（按文长动态计算阈值）
- AI 检测模式分 < 门槛

### 加权总分（满分 10）

| 维度 | 权重 | 检查内容 |
|------|------|----------|
| humanizer | 0.27 | 5 维人味评分（直接性/节奏/信任度/真实性/精炼度） |
| ai_check | 0.15 | 40+ AI 套话模式检测 |
| fabrication | 0.15 | 伪造 URL/来源/数据 |
| cross_reference | 0.12 | 事实-素材交叉验证（仅 TIER_EXTERNAL） |
| semantic_facts | 0.10 | cocobook 语义验证 |
| format | 0.07 | 结构完整性 |
| word_count | 0.07 | 字数达标 |
| jargon | 0.07 | 管理黑话/圈内术语检测 |

### 信息性检查（不阻断发布）

- GEO（生成引擎优化）— Frase 5 维模型
- 术语规范 — WordPress 中文术语表
- 事实引用 — advisory 级别的来源追溯
