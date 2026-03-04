#!/bin/bash
# skill-monitor/install.sh - One-click installer

set -euo pipefail

INSTALL_DIR="${HOME}/.openclaw/tools/skill-monitor"
echo "🔧 Installing OpenClaw Skill Monitor to: $INSTALL_DIR"

# Create directories / 创建目录
mkdir -p "$INSTALL_DIR"
mkdir -p "${INSTALL_DIR}/logs"

# Copy files / 复制文件
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$SCRIPT_DIR"/{monitor.sh,monitor.py,config.json,dashboard.html,README.md} "$INSTALL_DIR/"

# Make executable / 设置可执行权限
chmod +x "$INSTALL_DIR/monitor.sh" "$INSTALL_DIR/monitor.py"

# Add to PATH / Add alias to shell config
SHELL_RC="${HOME}/.$(basename $SHELL)rc"
if ! grep -q "skill-monitor" "$SHELL_RC" 2>/dev/null; then
  echo -e "\n# OpenClaw Skill Monitor\nalias skill-monitor='$INSTALL_DIR/monitor.sh'" >> "$SHELL_RC"
  echo "✅ Added alias to $SHELL_RC"
fi

# Create default config if not exists / 创建默认配置
[[ ! -f "${HOME}/.openclaw/tools/skill-monitor/config.json" ]] && \
  cp "$INSTALL_DIR/config.json" "${HOME}/.openclaw/tools/skill-monitor/"

echo -e "\n✅ Installation complete!"
echo -e "\n🚀 Usage:"
echo "   skill-monitor              # Start real-time monitor"
echo "   skill-monitor --skill real_time  # Filter by skill"
echo "   python $INSTALL_DIR/monitor.py --dashboard  # Web dashboard"
echo -e "\n📚 Docs: $INSTALL_DIR/README.md"
