#!/usr/bin/env bash
set -euo pipefail

# 文章管线 — 架构图渲染脚本
# 用法: bash assets/diagrams/render.sh [diagram_name]
# 不带参数则渲染全部 JSON 文件

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIFY_DIR="$HOME/Projects/archify/archify"
RENDERER="$ARCHIFY_DIR/renderers/architecture/render-architecture.mjs"

if [[ ! -f "$RENDERER" ]]; then
    echo "archify not found at $ARCHIFY_DIR"
    echo "Install: git clone https://github.com/tt-a1i/archify.git ~/Projects/archify && cd ~/Projects/archify/archify && npm install"
    exit 1
fi

render_one() {
    local json="$1"
    local name
    name="$(basename "$json" .json)"
    local html="$SCRIPT_DIR/${name}.html"

    echo "Rendering: $name"
    node "$RENDERER" "$json" "$html"
    echo "  -> $html"
}

if [[ $# -gt 0 ]]; then
    target="$SCRIPT_DIR/$1.json"
    if [[ ! -f "$target" ]]; then
        echo "Not found: $target"
        exit 1
    fi
    render_one "$target"
else
    for json in "$SCRIPT_DIR"/*.json; do
        [[ -f "$json" ]] && render_one "$json"
    done
fi
