#!/bin/bash
# MCP + Orchestrator health check for huawei-pc
# Deploy: cp to /usr/local/bin/, chmod +x, install systemd timer

MCP_URL="http://localhost:8087/message"
ORCH_URL="http://localhost:8102/api/v1/orchestrate"
LOG_TAG="mcp-health-check"
MAX_FAILS=2
STATE_FILE="/tmp/mcp-health-fails"

log() { echo "[$(date -Iseconds)] $*" | systemd-cat -t "$LOG_TAG"; }

check_mcp() {
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
        -X POST "$MCP_URL" \
        -H 'Content-Type: application/json' \
        -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' 2>/dev/null)
    [ "$code" = "200" ]
}

check_orch() {
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
        -X POST "$ORCH_URL" \
        -H 'Content-Type: application/json' \
        -d '{"task":"ping","agents":[{"role":"p","persona":"istj","prompt":"ping"}],"protocol":"sequential"}' 2>/dev/null)
    [ "$code" = "200" ]
}

# Read fail counter
fails=$(cat "$STATE_FILE" 2>/dev/null || echo 0)

mcp_ok=false
orch_ok=false

check_mcp && mcp_ok=true
check_orch && orch_ok=true

if $mcp_ok && $orch_ok; then
    echo 0 > "$STATE_FILE"
    exit 0
fi

fails=$((fails + 1))
echo "$fails" > "$STATE_FILE"

if [ "$fails" -lt "$MAX_FAILS" ]; then
    log "WARN: MCP=${mcp_ok} ORCH=${orch_ok} (fail ${fails}/${MAX_FAILS}, waiting)"
    exit 0
fi

# Restart
log "ALERT: MCP=${mcp_ok} ORCH=${orch_ok} — restarting services"

if ! $mcp_ok; then
    systemctl restart cocobook-mcp 2>/dev/null || \
        pkill -f "cocobook-mcp-server" 2>/dev/null
    log "Restarted cocobook-mcp"
fi

if ! $orch_ok; then
    systemctl restart agent-orchestrator 2>/dev/null
    log "Restarted agent-orchestrator"
fi

echo 0 > "$STATE_FILE"
