# Article Pipeline — 使用指南

> 面向操作者（人类或 AI agent）的日常使用手册。

## 前置条件

```bash
# 环境变量（~/.env 或 shell profile）
AP_DS_API_KEY=xxx          # GLM-5.1 API key (z.ai)
AP_WP_USERNAME=xxx         # WordPress 用户名
AP_WP_APP_PASSWORD=xxx     # WordPress 应用密码

# 依赖服务
# - cocobook MCP 运行中 (huawei-pc:8087)
# - SQLite DB 自动初始化
```

## 日常工作流

### 1. 添加选题

```bash
article-pipeline add --keyword "WordPress 全站编辑入门" \
                     --category tutorial \
                     --priority 1
```

品类选择参考 SYSTEM-DEFINITION.md 的决策树。priority: 1=普通, 2=重要, 3=紧急。

### 2. 批量执行

```bash
# 处理队列中下 5 个任务（research → outline → write → review）
article-pipeline run --limit 5

# 恢复某个卡住的任务
article-pipeline continue <task_id>

# 回滚超时任务
article-pipeline recover --max-minutes 30
```

### 3. 人工审查

```bash
# 启动审查 UI
article-pipeline review-server
# → http://localhost:8765
```

审查 UI 操作：
- **Approve** — 通过，进入发布队列
- **Request Revision** — 勾选问题 + 写反馈 → AI 自动修改 → 生成新版本
- **Auto-revise** — 基于系统检测建议自动修改（无需手写反馈）
- **Reject** — 永久拒绝，附原因

### 4. 发布

```bash
article-pipeline publish <task_id>
```

发布到 WordPress，自动转换为 Gutenberg 区块格式。

### 5. 查看状态

```bash
# 列出所有任务
article-pipeline list

# 按状态筛选
article-pipeline list --status reviewing

# 查看单个任务详情
article-pipeline status <task_id>

# 跳过任务
article-pipeline skip <task_id> --reason "素材不足"
```

## 任务状态流转

```
queued → researching → outlining → [outline_review] → writing → reviewing → done
                                                                     ↓
                                                                   stuck
```

- `outline_review`: 仅 TIER_EXTERNAL 品类触发人工闸门
- `stuck`: 连续失败或超时，需手动介入

## Trust Tier 使用

| Tier | 适用场景 | 行为 |
|------|----------|------|
| TIER_INTERNAL | 自有产品、通用技术、WordPress 生态 | LLM 可以用假设场景、类比说明问题 |
| TIER_EXTERNAL | 他人产品评测、外部工具介绍 | LLM 严格只用参考素材中的确认事实 |

Tier 由 category 自动判断：
- EXTERNAL: product-launch, announcement, brand-marketing, case-study, tool-review, resource-roundup, soft-article, marketing
- INTERNAL: 其余所有

## 风格覆盖

### 调整单篇文章风格

在 DB 中设置 meta_json 的 style_overrides 字段（通过代码或 review_server）：

```json
{
  "style_overrides": {
    "edge": 0.8,
    "warmth": -0.2
  }
}
```

### 理解风格维度

| 想要的效果 | 调哪个维度 | 方向 |
|-----------|-----------|------|
| 更犀利/有态度 | edge | 调高 (+0.5 ~ +1.0) |
| 更亲切/有温度 | warmth | 调高 (+0.5 ~ +0.8) |
| 更简洁/信息密集 | density | 调高 (+0.3 ~ +0.6) |
| 更口语化/轻松 | register | 调高 (+0.3 ~ +0.6) |
| 更有冲击力/节奏感 | energy | 调高 (+0.5 ~ +0.8) |
| 更克制/客观 | 所有维度 | 往负方向调 |

**实际有效的调整幅度**: 跨区间才有明显效果（如从 +0.2 调到 +0.7），同区间内微调（+0.2 到 +0.4）LLM 产出区别不大。

## 审查分数解读

### overall_score 范围

| 分数段 | 含义 | 建议动作 |
|--------|------|----------|
| 8.0+ | 优秀 | 直接发布 |
| 6.5 ~ 8.0 | 合格 | 检查 suggestions 后发布 |
| 5.0 ~ 6.5 | 需修改 | 按建议修改后重新审查 |
| < 5.0 | 质量差 | 考虑跳过或重写 |

### 常见问题与处理

| 问题 | 原因 | 处理 |
|------|------|------|
| fabrication_flags > 2 | LLM 编造了 URL/数据 | 删除编造内容或补充素材后重写 |
| humanizer < 30/50 | 文章太像 AI | Auto-revise 或手动改写高频 AI 模板句 |
| ai_check 分低 | "不是...而是..."等模板句过多 | 替换为多样化的表达方式 |
| cross_reference 分低 | EXTERNAL 文章引用了素材外的事实 | 删除未验证内容 |

## 配置文件

```yaml
# ~/.config/article-pipeline/config.yaml
deepseek:
  base_url: "https://api.z.ai/api/anthropic"
  model: "glm-5.1"
  temperature: 0.7

mcp:
  base_url: "http://192.168.1.230:8087"

wordpress:
  url: "https://wptea.com"
  username: "${AP_WP_USERNAME}"
  app_password: "${AP_WP_APP_PASSWORD}"
```

## 与内容日历的配合

modiqi VM 制定的内容节奏：
- 掘金: 2 次/月（技术深度）
- V2EX: 1 次/月（真诚分享）
- wpcommunity: 2 次/月（社区感）
- linuxjoy.com: 2 次/月（全品牌）

选题来源：
1. `article-pipeline add` 手动添加
2. 用户常见问题 + 搜索关键词机会
3. 产品更新触发（插件新版本 → product-launch 文章）
4. 竞品动态 + 行业趋势

## 故障排除

### Pipeline 卡住

```bash
# 查看卡住的任务
article-pipeline list --status stuck

# 回滚超时任务到上一步
article-pipeline recover --max-minutes 30
```

### API 调用失败

```bash
# 检查 API key
echo $AP_DS_API_KEY | head -c 5

# 检查 cocobook MCP 是否在线
curl -s http://192.168.1.230:8087/health
```

### 审查分数异常低

通常是素材不足导致 LLM 编造。解决方案：
1. 手动补充 research_note（通过 DB 或 review_server）
2. 降低品类预期（从 tutorial 改为 beginner 降低深度要求）
3. 跳过该选题（`article-pipeline skip <id> --reason "素材不足"`)
