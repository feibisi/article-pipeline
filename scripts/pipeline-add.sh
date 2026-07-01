#!/usr/bin/bash
# Article Pipeline - 添加任务脚本
# 用法: pipeline-add.sh KEYWORD CATEGORY [--priority N]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$PROJECT_DIR/.venv"

if [[ -f "$VENV/bin/activate" ]]; then
    source "$VENV/bin/activate"
fi

cd "$PROJECT_DIR"

# 参数检查
if [[ $# -lt 2 ]]; then
    echo "用法: $0 KEYWORD CATEGORY [--priority N]"
    echo "示例: $0 'Nginx缓存配置' tutorial --priority 1"
    exit 1
fi

KEYWORD="$1"
CATEGORY="$2"
PRIORITY="2"

# 解析可选参数
while [[ $# -gt 2 ]]; do
    case "$3" in
        --priority)
            PRIORITY="$4"
            shift 2
            ;;
        *)
            echo "未知选项: $3"
            exit 1
            ;;
    esac
done

python3 -c "
from article_pipeline.db import TaskDB
import sys

db = TaskDB()
task_id = db.add_task(
    keyword='$KEYWORD',
    category='$CATEGORY',
    platform='manual',
    priority=$PRIORITY,
    allow_duplicate=False
)

if task_id:
    print(f'✅ 任务已创建: #{task_id}')
    print(f'   关键词: $KEYWORD')
    print(f'   分类: $CATEGORY')
    print(f'   优先级: $PRIORITY')
else:
    print(f'⚠️ 任务已存在或创建失败')
    sys.exit(1)
"
