# skill-monitor
Monitor Agent skills in openClaw
# 🔹 基础：实时监控所有技能
# Basic: Monitor all skills in real-time
skill-monitor

# 🔹 过滤：只监控 real_time 技能
# Filter: Only monitor real_time skill
skill-monitor --skill real_time

# 🔹 导出：运行后导出 JSON 统计
# Export: Export stats to JSON after monitoring
skill-monitor --export json
# → 生成: skill_stats_20260303.json

# 🔹 仪表盘：启动 Web 界面
# Dashboard: Start web UI
python ~/.openclaw/tools/skill-monitor/monitor.py --dashboard
# → 打开: http://127.0.0.1:8899

# 🔹 高级：自定义配置 + 通知
# Advanced: Custom config + notifications
skill-monitor --config ~/my-monitor-config.json --notify

# 🔹 后台运行 + 日志
# Background mode + logging
nohup skill-monitor > ~/skill-monitor.log 2>&1 &
