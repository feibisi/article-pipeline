#!/usr/bin/bash
# Article Pipeline - 健康检查脚本
# 检查任务队列、成功率、失败任务等指标

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$PROJECT_DIR/.venv"

if [[ -f "$VENV/bin/activate" ]]; then
    source "$VENV/bin/activate"
fi

cd "$PROJECT_DIR"

python3 -c "
from article_pipeline.db import TaskDB
from datetime import datetime, timedelta
import json

db = TaskDB()
now = datetime.now()

# 统计数据
stats = {
    'queued': 0,
    'stuck': 0,
    'done_24h': 0,
    'failed_24h': 0,
    'avg_quality': 0,
}

# 队列中任务
queued = db.conn.execute(
    'SELECT COUNT(*) FROM tasks WHERE status=\"queued\"'
).fetchone()[0]
stats['queued'] = queued

# 卡住的任务 (>24h 非完成状态)
stuck = db.conn.execute(
    '''SELECT COUNT(*) FROM tasks
       WHERE status NOT IN ('done', 'skipped', 'published')
       AND created_at < datetime('now', '-24 hours')'''
).fetchone()[0]
stats['stuck'] = stuck

# 24小时内完成
done_24h = db.conn.execute(
    '''SELECT COUNT(*) FROM tasks
       WHERE status='done'
       AND confirmed_at > datetime('now', '-24 hours')'''
).fetchone()[0]
stats['done_24h'] = done_24h

# 24小时内失败/跳过
failed_24h = db.conn.execute(
    '''SELECT COUNT(*) FROM tasks
       WHERE status IN ('skipped', 'failed')
       AND created_at > datetime('now', '-24 hours')'''
).fetchone()[0]
stats['failed_24h'] = failed_24h

# 平均质量评分（24小时内）
quality_rows = db.conn.execute(
    '''SELECT passed FROM review_log
       WHERE created_at > datetime('now', '-24 hours')'''
).fetchall()
if quality_rows:
    stats['avg_quality'] = sum(r[0] for r in quality_rows) / len(quality_rows)

# 输出
print('=== Article Pipeline 健康状态 ===')
print(f'队列中任务: {stats[\"queued\"]}')
print(f'卡住任务 (>24h): {stats[\"stuck\"]}')
print(f'24h 完成: {stats[\"done_24h\"]}')
print(f'24h 失败: {stats[\"failed_24h\"]}')
print(f'平均质量评分: {stats[\"avg_quality\"]:.1f}')

# 健康判断
health = 'healthy'
if stats['stuck'] > 5:
    health = 'unhealthy'
elif stats['failed_24h'] > stats['done_24h']:
    health = 'degraded'
elif stats['avg_quality'] < 7.0:
    health = 'warning'

print(f'\\n状态: {health.upper()}')

# 如果不健康，显示卡住的任务
if health != 'healthy':
    stuck_tasks = db.conn.execute(
        '''SELECT id, keyword, status, skip_reason
           FROM tasks
           WHERE status NOT IN ('done', 'skipped', 'published')
           AND created_at < datetime('now', '-24 hours')
           LIMIT 5'''
    ).fetchall()
    if stuck_tasks:
        print(f'\\n卡住任务示例:')
        for t in stuck_tasks:
            print(f'  #{t[0]}: {t[1]} ({t[2]})')
            if t[3]:
                print(f'    原因: {t[3][:60]}...')
"

# 返回健康状态码
exit $?
