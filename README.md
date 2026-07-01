# Article Pipeline

AI 原生中文技术内容生产系统 — 从关键词到 WordPress 发布，全链路自动化。

## 架构

```
keyword → [Research] → [Outline] → [Write] → [Self-Review] → (Human Review)
                                    ↑                              │
                                    └── Revise ← Feedback ←────────┘
                                                              │
                                                         Approve → [Publish]
```

**三层控制模型**:
- 事实层 (Trust Tier) — 能不能写：信息来源边界
- 风格层 (Style System) — 怎么写：语气、节奏、立场强度
- 质量层 (Review Module) — 写得好不好：10 维自动评分

## 文档

| 文档 | 内容 |
|------|------|
| [docs/SYSTEM-DEFINITION.md](docs/SYSTEM-DEFINITION.md) | 系统定义：设计哲学、核心假设、模块关系、品类体系、质量标准 |
| [docs/STYLE-SYSTEM.md](docs/STYLE-SYSTEM.md) | 文风格调系统技术说明书：五维坐标、注入分层、审美概念、API |
| [docs/USAGE-GUIDE.md](docs/USAGE-GUIDE.md) | 使用指南：日常工作流、配置、故障排除 |
| [docs/STYLE-AUDIT.md](docs/STYLE-AUDIT.md) | 审计报告：已知问题、改进路线 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 任务计划：P0~P3 分级，依赖关系，验收标准 |

## 模块

| 模块 | 文件 | 职责 |
|------|------|------|
| DB | `db.py` | SQLite 任务队列、版本追踪、反馈日志 |
| Research | `research.py` | cocobook MCP + DDG 搜索 + 内容农场过滤 |
| Outline | `outline.py` | 结构化大纲（claim/audience/hook + 段落骨架） |
| Style | `style.py` | 五维坐标风格系统（疏密/冷暖/动静/雅俗/锐钝） |
| Writer | `writer.py` | LLM 写作（Trust Tier + Style + Genre Rules） |
| Review | `review/` | 10 维评分：AI 检测、编造、humanizer、术语、GEO 等 |
| Pipeline | `pipeline.py` | 编排全流程、重试逻辑 |
| Publish | `publish.py` | WordPress REST API（Gutenberg 区块格式） |
| Server | `review_server.py` | Web UI：审查队列、版本历史、修订工作流 |

## 快速开始

```bash
# 安装
pip install -e .

# 配置
# 设置环境变量: AP_DS_API_KEY, AP_WP_USERNAME, AP_WP_APP_PASSWORD

# 添加选题
article-pipeline add --keyword "WordPress 全站编辑入门" --category tutorial

# 执行管线
article-pipeline run --limit 5

# 审查
article-pipeline review-server  # → http://localhost:8765
```

## CLI

```
article-pipeline add --keyword "..." --category <品类> [--priority 1|2|3]
article-pipeline list [--status queued|reviewing|done|stuck]
article-pipeline run [--limit 5]
article-pipeline continue <task_id>
article-pipeline recover [--max-minutes 30]
article-pipeline review-server
article-pipeline publish <task_id>
article-pipeline skip <task_id> --reason "..."
```

## 品类（21 种）

搜索型: tutorial, guide, troubleshooting, comparison, beginner, listicle, resource-roundup, tool-review
相遇型: opinion, trend, thought-leadership, editorial, case-study, marketing, brand-marketing, soft-article, product-launch
告知型: announcement, news
专题型: wp-tech, book-knowledge

详细品类选择决策树见 [SYSTEM-DEFINITION.md](docs/SYSTEM-DEFINITION.md#品类选择决策树)。

## 评分维度（10 维）

| 维度 | 权重 | 检查内容 |
|------|------|----------|
| humanizer | 0.27 | 5 维人味评分（直接性/节奏/信任度/真实性/精炼度） |
| ai_check | 0.15 | 40+ AI 套话模式 |
| fabrication | 0.15 | 伪造 URL/来源/数据 |
| cross_reference | 0.12 | 事实-素材交叉验证 |
| semantic_facts | 0.10 | cocobook 语义验证 |
| format | 0.07 | H2/H3 结构、段落数 |
| word_count | 0.07 | 字数达标 |
| jargon | 0.07 | 管理黑话检测 |

硬门控: humanizer < 30/50 或 fabrication > 2 flags → 自动拒绝。

## 依赖

- Python 3.11+
- GLM-5.1 via z.ai API (Anthropic-compatible endpoint)
- cocobook MCP (huawei-pc:8087) — 全文检索 + 语义搜索
- WordPress REST API — 发布
- translate VM — Gutenberg 转换（备选）

## 开发

```bash
pip install -e ".[test]"
pytest tests/ -v
```
