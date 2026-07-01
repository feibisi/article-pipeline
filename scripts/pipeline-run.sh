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

if [[ "$DRY_RUN" == "true" ]]; then
    echo "=== 预览模式 ==="
    python3 -c "
from article_pipeline.db import TaskDB
db = TaskDB()
tasks = db.get_next_batch(limit=$BATCH_SIZE)
print(f'待处理任务: {len(tasks)}')
for t in tasks:
    print(f'  #{t[\"id\"]}: {t[\"keyword\"]} ({t[\"category\"]})')
"
    exit 0
fi

# 批量运行
echo "=== Article Pipeline 批量生产 ==="
echo "批次大小: $BATCH_SIZE"
echo "优先级: $PRIORITY"
if [[ -n "$CATEGORY" ]]; then
    echo "分类: $CATEGORY"
fi
echo

python3 -c "
from article_pipeline.db import TaskDB
from article_pipeline.pipeline import Pipeline
import json

db = TaskDB()
pipeline = Pipeline(db)

# 获取待处理任务
tasks = db.get_next_batch(limit=$BATCH_SIZE)
print(f'待处理任务: {len(tasks)}')

if not tasks:
    print('没有待处理任务')
    exit(0)

results = {'success': [], 'failed': [], 'skipped': []}

for task in tasks:
    task_id = task['id']
    keyword = task['keyword']
    print(f'\\n=== 任务 #{task_id}: {keyword} ===')

    try:
        result = pipeline.run(task_id)
        results['success'].append(task_id)
        print(f'✅ 完成')
    except Exception as e:
        results['failed'].append((task_id, str(e)))
        print(f'❌ 失败: {e}')

print(f'\\n=== 批次结果 ===')
print(f'成功: {len(results[\"success\"])}')
print(f'失败: {len(results[\"failed\"])}')
print(f'跳过: {len(results[\"skipped\"])}')

if results['failed']:
    print(f'\\n失败任务:')
    for task_id, reason in results['failed']:
        print(f'  #{task_id}: {reason}')
"

echo
echo "=== 批次完成 ==="
