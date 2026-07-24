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
import json, sys
from article_pipeline.db import TaskDB, HUMAN_GATE_STATES

db = TaskDB()

counts = db.status_counts()
queued = counts.get('queued', 0)

# 真正卡住的任务：用 db.get_stuck_tasks（覆盖整条级联，排除人工闸门），
# 而不是"创建超过 24h 且未完成"——后者会把等人审的任务算成故障。
stalled = db.get_stuck_tasks(max_minutes=60)

# 等人处理的任务（不是故障，但需要提醒人）
waiting_human = sum(counts.get(s, 0) for s in HUMAN_GATE_STATES)

# published_at 才是发布时间；confirmed_at 是进入 reviewing 的时间。
done_24h = db.conn.execute(
    '''SELECT COUNT(*) FROM tasks
       WHERE status IN ('done','published')
       AND published_at > datetime('now', '-24 hours')'''
).fetchone()[0]

failed_24h = db.conn.execute(
    '''SELECT COUNT(*) FROM tasks
       WHERE status IN ('skipped','rejected')
       AND created_at > datetime('now', '-24 hours')'''
).fetchone()[0]

# review_log.passed 是 0/1，不是 10 分制。旧版拿它和 7.0 比较，
# 于是健康度永远最多只能是 WARNING。
rows = db.conn.execute(
    '''SELECT passed FROM review_log
       WHERE created_at > datetime('now', '-24 hours')'''
).fetchall()
pass_rate = (sum(r[0] for r in rows) / len(rows)) if rows else None

print('=== Article Pipeline 健康状态 ===')
print(f'队列中任务   : {queued}')
print(f'卡住任务(>1h): {len(stalled)}')
print(f'等人处理     : {waiting_human}')
print(f'24h 发布     : {done_24h}')
print(f'24h 失败/跳过: {failed_24h}')
print('24h 自审通过率: ' + (f'{pass_rate*100:.0f}%' if pass_rate is not None else 'n/a (无自审记录)'))
print()
print('状态分布:')
for st in sorted(counts):
    print(f'  {st:<14} {counts[st]}')

health = 'healthy'
if len(stalled) > 5:
    health = 'unhealthy'
elif len(stalled) > 0:
    health = 'degraded'
elif failed_24h > done_24h and failed_24h > 0:
    health = 'degraded'
elif pass_rate is not None and pass_rate < 0.5:
    health = 'warning'
elif queued == 0:
    # 人一停，管线就空转：这是本项目最常见的"故障"
    health = 'warning'

print()
print(f'状态: {health.upper()}')
if queued == 0:
    print('提示: 队列为空，没有自动选题来源，管线会一直空转。')

if stalled:
    print()
    print('卡住任务:')
    for t in stalled[:5]:
        meta = json.loads(t.get('meta_json') or '{}')
        last = meta.get('last_error', {})
        mins = t.get('stuck_minutes')
        print(f'  #{t[\"id\"]}: {t[\"keyword\"]} ({t[\"status\"]}, idle {mins if mins is not None else \"?\"}min)')
        if last:
            print(f'    最后错误 [{last.get(\"stage\",\"?\")}]: {str(last.get(\"error\",\"\"))[:70]}')
    print('  修复: ap recover --dry-run  然后  ap recover')

sys.exit(0 if health in ('healthy', 'warning') else 1)
"
