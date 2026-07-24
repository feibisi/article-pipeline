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
    echo "用法: $0 KEYWORD CATEGORY [--priority N] [--platform P] [--skip-filter]"
    echo "示例: $0 'Nginx缓存配置' tutorial --priority 1"
    exit 1
fi

KEYWORD="$1"
CATEGORY="$2"
shift 2
PRIORITY="2"
PLATFORM="wptea"
SKIP_FILTER="0"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --priority)  PRIORITY="$2"; shift 2 ;;
        --platform)  PLATFORM="$2"; shift 2 ;;
        --skip-filter) SKIP_FILTER="1"; shift ;;
        *) echo "未知选项: $1"; exit 1 ;;
    esac
done

# 通过环境变量传参：直接拼进 python -c 的字符串会在关键词含单引号时
# 语法错误，并且构成代码注入。
export AP_KEYWORD="$KEYWORD"
export AP_CATEGORY="$CATEGORY"
export AP_PLATFORM="$PLATFORM"
export AP_PRIORITY="$PRIORITY"
export AP_SKIP_FILTER="$SKIP_FILTER"

# 走 Pipeline.add_task 而不是 db.add_task：前者包含选题去重 + 选题价值过滤，
# 直接打 db 层会绕过两道闸门。
python3 -c "
import os, sys
from article_pipeline.pipeline import Pipeline

p = Pipeline()
task_id = p.add_task(
    keyword=os.environ['AP_KEYWORD'],
    category=os.environ['AP_CATEGORY'],
    platform=os.environ['AP_PLATFORM'],
    priority=int(os.environ['AP_PRIORITY']),
    skip_filter=os.environ['AP_SKIP_FILTER'] == '1',
)
if not task_id:
    print('任务未创建（重复选题或未通过选题过滤）')
    sys.exit(1)
print(f'任务已创建: #{task_id}')
"
