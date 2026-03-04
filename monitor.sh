#!/bin/bash
# skill-monitor/monitor.sh - Real-time OpenClaw skill invocation monitor
# Usage: ./monitor.sh [--skill NAME] [--format json|table] [--notify]

set -euo pipefail

# ============ 配置 / Config ============
CONFIG_FILE="${HOME}/.openclaw/tools/skill-monitor/config.json"
LOG_DIR="${HOME}/.openclaw/tools/skill-monitor/logs"
SKILL_LOG_DIR="/tmp"  # Where skills write their logs
GATEWAY_LOG="${HOME}/.openclaw/logs/gateway.log"

# 颜色 / Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m' # No Color

# 解析参数 / Parse args
FILTER_SKILL=""
OUTPUT_FORMAT="table"
ENABLE_NOTIFY=false
while [[ $# -gt 0 ]]; do
  case $1 in
    --skill|-s) FILTER_SKILL="$2"; shift 2 ;;
    --format|-f) OUTPUT_FORMAT="$2"; shift 2 ;;
    --notify|-n) ENABLE_NOTIFY=true; shift ;;
    --help|-h) echo "Usage: $0 [--skill NAME] [--format json|table] [--notify]"; exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# 初始化 / Init
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SESSION_LOG="$LOG_DIR/monitor_${TIMESTAMP}.log"

echo -e "${CYAN}🔍 OpenClaw Skill Monitor${NC} — Started at $(date)"
echo "Filter: ${FILTER_SKILL:-all} | Format: $OUTPUT_FORMAT | Notify: $ENABLE_NOTIFY"
echo "Logging to: $SESSION_LOG"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 监控函数 / Monitor function
monitor_skills() {
  # 监控所有 *_skill.log 文件 / Monitor all *_skill.log files
  find "$SKILL_LOG_DIR" -name "*_skill.log" -type f 2>/dev/null | while read -r logfile; do
    skill_name=$(basename "$logfile" _skill.log)
    
    # 应用过滤 / Apply filter
    [[ -n "$FILTER_SKILL" && "$skill_name" != "$FILTER_SKILL" ]] && continue
    
    # 实时追踪日志 / Tail the log
    tail -F "$logfile" 2>/dev/null | while read -r line; do
      # 解析 JSON 输出 / Parse JSON output
      if echo "$line" | grep -q '^{'; then
        timestamp=$(date '+%H:%M:%S')
        
        # 提取关键字段 / Extract key fields
        skill=$(echo "$line" | jq -r '.skill // "unknown"' 2>/dev/null || echo "$skill_name")
        exec_time=$(echo "$line" | jq -r '.time // "N/A"' 2>/dev/null)
        pid=$(echo "$line" | jq -r '._debug_pid // "N/A"' 2>/dev/null)
        
        # 格式化输出 / Format output
        if [[ "$OUTPUT_FORMAT" == "json" ]]; then
          echo "{\"ts\":\"$(date -Iseconds)\",\"skill\":\"$skill\",\"time\":\"$exec_time\",\"pid\":\"$pid\",\"raw\":$line}"
        else
          echo -e "${GREEN}[$timestamp]${NC} ⏰ ${BLUE}$skill${NC} executed • time: ${YELLOW}$exec_time${NC} • PID: $pid"
        fi
        
        # 记录到会话日志 / Log to session file
        echo "[$timestamp] $skill executed: $line" >> "$SESSION_LOG"
        
        # 通知 / Notify
        if [[ "$ENABLE_NOTIFY" == true ]]; then
          notify-send "Skill Called: $skill" "Time: $exec_time" -t 3000 2>/dev/null || true
          # 可选：播放声音 / Optional: play sound
          # paplay /usr/share/sounds/freedesktop/stereo/dialog-information.oga 2>/dev/null || true
        fi
      fi
    done &
  done
}

# 同时监控 gateway 日志中的技能匹配事件 / Also monitor gateway logs for skill matching
monitor_gateway() {
  if [[ -f "$GATEWAY_LOG" ]]; then
    tail -F "$GATEWAY_LOG" 2>/dev/null | grep -i "skill\|trigger\|executing" | while read -r line; do
      timestamp=$(date '+%H:%M:%S')
      echo -e "${YELLOW}[$timestamp] 🧠 Gateway:${NC} ${line}" >> "$SESSION_LOG"
      [[ "$OUTPUT_FORMAT" != "json" ]] && echo -e "${YELLOW}[$timestamp] 🧠 Gateway:${NC} ${line}"
    done &
  fi
}

# 启动监控 / Start monitoring
echo -e "${GREEN}✅ Monitoring started. Press Ctrl+C to stop.${NC}"
monitor_skills
monitor_gateway

# 等待中断 / Wait for interrupt
trap "echo -e '\n${RED}⏹️  Monitoring stopped.${NC}'; exit 0" INT TERM
wait
