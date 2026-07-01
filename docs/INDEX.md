# Article Pipeline — 文档索引

> 所有文档的导航入口。按用途分类。

## 系统理解（先读这些）

| 文档 | 用途 | 读者 |
|------|------|------|
| [SYSTEM-DEFINITION.md](SYSTEM-DEFINITION.md) | 系统是什么、为什么这样设计、三层控制模型、品类体系 | 所有人 |
| [STYLE-SYSTEM.md](STYLE-SYSTEM.md) | 文风格调系统技术说明书：五维坐标、注入分层、API | 开发/调参 |
| [ARCHITECTURE-GAPS.md](ARCHITECTURE-GAPS.md) | 架构缺层分析：synthesis/framework/prosody 三层缺失诊断与重构方向 | 架构决策 |

## 日常操作（动手时看这些）

| 文档 | 用途 | 读者 |
|------|------|------|
| [USAGE-GUIDE.md](USAGE-GUIDE.md) | CLI 命令、工作流、配置、故障排除 | 操作者（人/AI） |

## 规划与决策（方向性文档）

| 文档 | 用途 | 读者 |
|------|------|------|
| [OVERHAUL-PLAN.md](OVERHAUL-PLAN.md) | 完整改造执行方案：级联编译、可插拔品类域、实施表、验收标准、Studio 协作契约 | 执行者/决策者 |
| [EVOLUTION-PLAN.md](EVOLUTION-PLAN.md) | A/B/C/D 四条发展路径、反 slop 策略、架构备忘 | 决策者 |
| [ROADMAP.md](ROADMAP.md) | 近期执行任务清单（P0~P4）、依赖关系、验收标准 | 执行者 |
| [AUDIT-RESULTS-AND-NEXT.md](AUDIT-RESULTS-AND-NEXT.md) | 2026-07-01 文档审查结果、14 项修复清单、子代理任务拆分、新会话启动说明 | 执行者 |
| [STYLE-AUDIT.md](STYLE-AUDIT.md) | 风格系统审计：已知问题、改进建议 | 开发 |

## 外部设计文档（不在本目录）

| 文档 | 位置 | 内容 |
|------|------|------|
| article-pipeline-style-design.md | `~/docs/ai-context/` | 文风格调系统原始设计稿（含完整映射规则推导过程） |

## 集群记忆相关条目

| ID | 标题 | 类型 |
|----|------|------|
| #3503 | 写作管线下一阶段方向：从"写得好"到"值得读" | decision |
| #3504 | 小说/剧本/故事/电影需独立 workspace | decision |
| #3505 | 创意写作管线资源盘点与准备工作 | config |
| #3693 | 文风格调: 5维坐标系替代 if-else 体裁规则 | decision |
| #3691 | LLM 编造根因：writer prompt 冲突 + outline 截断 | lesson |
| #2932 | 内容日历：掘金+V2EX+wpcommunity+linuxjoy | doc |
| #4203 | article-pipeline 不再局限 WP，核心竞争力定义 | decision |
| #4204 | 过度工程化教训：4 个月 0 产出 | lesson |
| #4205 | 即时执行计划：Claude 换模型 + 本周跑 5 篇 | decision |
| #4206 | 反 slop 策略：value_density 评分 + differentiation 闸门 | decision |
| #4207 | 写作管线架构缺三层：synthesis/framework/prosody | decision |
| #4208 | 创作系统架构：独立管线 + 共享核心库(creative-core) | decision |
| #4209 | 工程vs创作双轨约束模型：硬约束保底线+软约束提上限 | decision |
| #4210 | 素材策略：archify(技术图)+xiaohei-scenes(共鸣图)+Studio(品牌) | decision |
| #4211 | 双轨约束模型：工程层(硬约束)保底线 + 创作层(软约束)提上限 | decision |
| #4212 | 素材策略三级视觉编译：本地工程图/Studio创意图/截图证据/数据图 | decision |

## 文档维护规则

- 系统变更后更新 SYSTEM-DEFINITION.md（架构/模块/品类变化）
- style.py 改动后更新 STYLE-SYSTEM.md（预设/API 变化）
- 完成 ROADMAP 任务后标记完成并更新验收结果
- EVOLUTION-PLAN 按季度复审，调整路径优先级
- 本索引在新增/删除文档时同步更新
