# Article Pipeline 运维手册

## 快速开始

### 1. 添加任务

```bash
# 添加单个任务
./scripts/pipeline-add.sh "关键词" 分类

# 高优先级任务
./scripts/pipeline-add.sh "Nginx缓存配置" tutorial --priority 1
```

### 2. 手动运行批次

```bash
# 处理队列中的任务（默认3个）
./scripts/pipeline-run.sh

# 处理更多任务
./scripts/pipeline-run.sh --batch 10

# 仅预览不执行
./scripts/pipeline-run.sh --dry-run
```

### 3. 健康检查

```bash
# 查看队列状态和成功率
./scripts/pipeline-monitor.sh
```

## Systemd 定时任务

### 启用定时任务

```bash
# 重新加载 systemd 配置
systemctl --user daemon-reload

# 启动定时任务
systemctl --user enable --now article-pipeline.timer

# 查看下次运行时间
systemctl --user list-timers article-pipeline.timer

# 查看日志
journalctl --user -u article-pipeline.service -f
```

### 定时任务配置

默认每天运行 4 次：06:00, 12:00, 18:00, 00:00

修改 `~/.config/systemd/user/article-pipeline.timer` 调整。

### 手动触发

```bash
# 立即运行一次
systemctl --user start article-pipeline.service
```

## 监控指标

| 指标 | 说明 | 健康阈值 |
|------|------|----------|
| queued | 队列中任务数 | < 20 |
| stuck | 卡住任务 (>24h) | < 5 |
| done_24h | 24h 完成数 | > 0 |
| failed_24h | 24h 失败数 | < 完成 |
| avg_quality | 平均质量评分 | > 7.0 |

## 任务状态流转

```
queued → researching → synthesizing → framework → prosody → compiling
→ outlining → writing → reviewing → done
         ↓         ↓        ↓      ↓
       skipped   skipped  skipped skipped
```

## 常见问题

### Q: 任务卡住怎么办？

```bash
# 查看卡住的任务
./scripts/pipeline-monitor.sh

# 重试单个任务
python3 -c "from article_pipeline.pipeline import Pipeline; Pipeline().resume(task_id)"
```

### Q: 如何批量导入任务？

创建 JSON 文件 `tasks.json`：

```json
[
  {"keyword": "关键词1", "category": "tutorial", "priority": 2},
  {"keyword": "关键词2", "category": "guide", "priority": 1}
]
```

然后运行：

```bash
python3 -c "
from article_pipeline.db import TaskDB
import json
db = TaskDB()
for t in json.load(open('tasks.json')):
    db.add_task(**t, platform='batch', allow_duplicate=False)
"
```

### Q: 如何清理旧任务？

```bash
# 删除 30 天前的已完成任务
python3 -c "
from article_pipeline.db import TaskDB
from datetime import datetime, timedelta
db = TaskDB()
cutoff = (datetime.now() - timedelta(days=30)).isoformat()
db.conn.execute('DELETE FROM tasks WHERE status=\"done\" AND confirmed_at < ?', (cutoff,))
db.conn.commit()
print('已清理旧任务')
"
```
