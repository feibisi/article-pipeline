#!/usr/bin/bash
# Article Pipeline - 批量生产脚本
# 用法: pipeline-run.sh [--batch N] [--category CAT] [--priority N]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$PROJECT_DIR/.venv"

# 默认参数
BATCH_SIZE=3
CATEGORY=""
PRIORITY=2
DRY_RUN=false

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --batch)
            BATCH_SIZE="$2"
            shift 2
            ;;
        --category)
            CATEGORY="$2"
            shift 2
            ;;
        --priority)
            PRIORITY="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            echo "用法: $0 [选项]"
            echo "选项:"
            echo "  --batch N       批量处理 N 个任务 (默认: 3)"
            echo "  --category CAT  指定分类"
            echo "  --priority N    指定优先级 (默认: 2)"
            echo "  --dry-run       仅显示将要执行的任务"
            exit 0
            ;;
        *)
            echo "未知选项: $1"
            exit 1
            ;;
    esac
done

# 激活 venv
if [[ -f "$VENV/bin/activate" ]]; then
    source "$VENV/bin/activate"
else
    echo "错误: 虚拟环境不存在: $VENV"
    echo "请先运行: python3 -m venv .venv && .venv/bin/pip install -e ."
    exit 1
fi

# 导入 pipeline
cd "$PROJECT_DIR"

# 参数通过环境变量传给 Python，避免把 shell 变量拼进源码（注入 + 引号问题）
export AP_BATCH_SIZE="$BATCH_SIZE"
export AP_CATEGORY="$CATEGORY"
export AP_MAX_PRIORITY="$PRIORITY"

if [[ "$DRY_RUN" == "true" ]]; then
    echo "=== 预览模式（不占用任务） ==="
    # 注意: 旧版这里调用 get_next_batch()，它会把任务状态改成 researching，
    # 即"预览"实际上抢占了任务。peek_next_batch() 只读。
    python3 -c "
import os
from article_pipeline.db import TaskDB
db = TaskDB()
tasks = db.peek_next_batch(
    limit=int(os.environ['AP_BATCH_SIZE']),
    category=os.environ.get('AP_CATEGORY') or None,
    max_priority=int(os.environ['AP_MAX_PRIORITY']),
)
print(f'待处理任务: {len(tasks)}')
for t in tasks:
    print(f'  #{t[\"id\"]} P{t[\"priority\"]} [{t[\"category\"]}] {t[\"keyword\"]}')
"
    exit 0
fi

# 批量运行
echo "=== Article Pipeline 批量生产 ==="
echo "批次大小: $BATCH_SIZE"
echo "优先级上限: $PRIORITY"
if [[ -n "$CATEGORY" ]]; then
    echo "分类: $CATEGORY"
fi
echo

# Pipeline.run() 自己会 claim 任务并逐阶段推进。
# 旧版先调 db.get_next_batch() 抢占一批，再对每个任务调 pipeline.run(task_id)
# —— run() 的签名是 run(limit=5)，task_id 被当成 limit，于是又抢占了一批，
# 造成重复 claim 且第一批任务永远无人推进。
python3 -c "
import os, sys
from article_pipeline.db import TaskDB
from article_pipeline.pipeline import Pipeline

db = TaskDB()
pipeline = Pipeline(db)
results = pipeline.run(
    limit=int(os.environ['AP_BATCH_SIZE']),
    category=os.environ.get('AP_CATEGORY') or None,
    max_priority=int(os.environ['AP_MAX_PRIORITY']),
)

print()
print('=== 批次结果 ===')
print(f'阶段推进次数: {len(results)}')
counts = db.status_counts()
for st in sorted(counts):
    print(f'  {st:<14} {counts[st]}')

failed = [t for t in db.list_tasks(status='skipped')]
recent = failed[-int(os.environ['AP_BATCH_SIZE']):] if failed else []
if recent:
    print()
    print('最近 skipped 任务（含失败原因）:')
    for t in recent:
        print(f'  #{t[\"id\"]}: {t[\"keyword\"]} — {t.get(\"skip_reason\") or \"?\"}')
"

echo
echo "=== 批次完成 ==="
