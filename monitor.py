#!/usr/bin/env python3
# skill-monitor/monitor.py - Advanced OpenClaw skill monitor with export & dashboard
# Usage: python monitor.py [--skill NAME] [--export json] [--dashboard]

import json
import os
import sys
import time
import argparse
import logging
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import threading
import webbrowser

# ============ Path expansion helper ============
def expand_path(path):
    """Expand $HOME and ~ in paths"""
    if path and isinstance(path, str):
        # Replace $HOME with actual home directory
        if "$HOME" in path:
            path = path.replace("$HOME", str(Path.home()))
        # Also handle ~
        path = os.path.expanduser(path)
    return path

# ============ 配置 / Config ============
DEFAULT_CONFIG = {
    "skill_log_dir": "/tmp",
    "gateway_log": str(Path.home() / ".openclaw/logs/gateway.log"),
    "output_dir": str(Path.home() / ".openclaw/tools/skill-monitor/logs"),
    "filters": {
        "skills": [],
        "min_interval_sec": 0,
        "exclude_debug_fields": True
    },
    "notifications": {
        "enabled": False,
        "webhook_url": None,
        "sound": False
    },
    "dashboard": {
        "enabled": True,
        "port": 8899,
        "auto_open": True
    }
}

class SkillMonitor:
    def __init__(self, config_path=None):
        self.config = self._load_config(config_path)
        self.stats = defaultdict(lambda: {"count": 0, "last_call": None, "params": []})
        self.running = False
        self.filter_skill = None
        self.last_alert_time = defaultdict(float)  # For deduplication
        self._setup_logging()
        
    def _load_config(self, path):
        config = DEFAULT_CONFIG.copy()
        if path and Path(path).exists():
            with open(path) as f:
                user_config = json.load(f)
                for key in user_config:
                    if isinstance(user_config[key], dict):
                        config[key].update(user_config[key])
                    else:
                        config[key] = user_config[key]
        
        # Expand paths in config
        config["gateway_log"] = expand_path(config["gateway_log"])
        config["output_dir"] = expand_path(config["output_dir"])
        config["skill_log_dir"] = expand_path(config["skill_log_dir"])
        
        return config
    
    def _setup_logging(self):
        os.makedirs(self.config["output_dir"], exist_ok=True)
        log_file = Path(self.config["output_dir"]) / f"monitor_{datetime.now():%Y%m%d_%H%M%S}.log"
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"🔍 Skill Monitor started — Config: {self.config['output_dir']}")
    
    def _should_alert(self, skill_name):
        """Check if enough time has passed since last alert for this skill"""
        min_interval = self.config["filters"]["min_interval_sec"]
        if min_interval <= 0:
            return True
        
        now = time.time()
        if now - self.last_alert_time.get(skill_name, 0) >= min_interval:
            self.last_alert_time[skill_name] = now
            return True
        return False
    
    def _parse_skill_data(self, line, source_file):
        """Parse JSON data from a line, extract skill information"""
        line = line.strip()
        if not line.startswith('{'):
            return None, None
        
        try:
            data = json.loads(line)
            
            # Try different possible field names for skill
            skill_name = (data.get("skill") or 
                         data.get("skill_name") or 
                         data.get("name") or 
                         data.get("function"))
            
            if not skill_name:
                return None, None
            
            # Apply skill filter
            if self.filter_skill and skill_name != self.filter_skill:
                return None, None
            
            # Apply skills whitelist from config
            if self.config["filters"]["skills"] and skill_name not in self.config["filters"]["skills"]:
                return None, None
            
            # Remove debug fields if configured
            if self.config["filters"]["exclude_debug_fields"]:
                data = {k: v for k, v in data.items() if not k.startswith('_debug')}
            
            return skill_name, data
            
        except json.JSONDecodeError:
            return None, None
    
    def _on_skill_invoked(self, skill_name, data):
        """Handle a skill invocation"""
        # Check deduplication
        if not self._should_alert(skill_name):
            return
        
        timestamp = datetime.now().isoformat()
        self.stats[skill_name]["count"] += 1
        self.stats[skill_name]["last_call"] = timestamp
        
        # Store relevant params (limit to last 10 to save memory)
        params = self.stats[skill_name]["params"]
        params.append(data.get("time", "N/A"))
        if len(params) > 10:
            params.pop(0)
        
        output = {
            "timestamp": timestamp,
            "skill": skill_name,
            "data": data,
            "stats": {"total_calls": self.stats[skill_name]["count"]}
        }
        
        # Console output
        print(f"\n{timestamp} ⏰ {skill_name} executed (call #{self.stats[skill_name]['count']})")
        if data:
            print(f"   └─ Data: {json.dumps(data, indent=2, ensure_ascii=False)}")
        
        # Log to file
        self.logger.info(json.dumps(output, ensure_ascii=False))
        
        # Send notifications
        if self.config["notifications"]["enabled"]:
            self._send_notification(skill_name, data)
    
    def _send_notification(self, skill_name, data):
        """Send webhook notification"""
        if self.config["notifications"]["webhook_url"]:
            try:
                import requests
                requests.post(
                    self.config["notifications"]["webhook_url"],
                    json={"skill": skill_name, "data": data, "timestamp": datetime.now().isoformat()},
                    timeout=5
                )
                self.logger.debug(f"📤 Notification sent for {skill_name}")
            except Exception as e:
                self.logger.debug(f"⚠️ Notification failed: {e}")
        
        if self.config["notifications"]["sound"]:
            try:
                import subprocess
                subprocess.run(
                    ["paplay", "/usr/share/sounds/freedesktop/stereo/dialog-information.oga"],
                    capture_output=True, timeout=2
                )
            except Exception as e:
                self.logger.debug(f"⚠️ Sound failed: {e}")
    
    def _monitor_file(self, filepath, skill_name):
        """Monitor a specific skill log file"""
        import time
        filepath = Path(filepath)
        
        if not filepath.exists():
            self.logger.warning(f"⚠️ File not found: {filepath}")
            return
        
        self.logger.info(f"📝 Monitoring file: {filepath}")
        
        try:
            with open(filepath, 'r') as f:
                # Go to end of file
                f.seek(0, 2)
                
                while self.running:
                    line = f.readline()
                    if line:
                        skill_name, data = self._parse_skill_data(line, filepath)
                        if skill_name and data:
                            self._on_skill_invoked(skill_name, data)
                    else:
                        time.sleep(0.1)
        except Exception as e:
            self.logger.error(f"❌ Error monitoring {filepath}: {e}")
    
    def _monitor_gateway(self):
        """Monitor the gateway.log file for skill entries"""
        gateway_log = Path(self.config["gateway_log"])
        
        # Wait for file to exist
        max_wait = 30
        waited = 0
        while not gateway_log.exists() and waited < max_wait:
            time.sleep(1)
            waited += 1
            if waited % 5 == 0:
                self.logger.info(f"⏳ Waiting for gateway log: {gateway_log}")
        
        if not gateway_log.exists():
            self.logger.warning(f"⚠️ Gateway log not found: {gateway_log}")
            return
        
        self.logger.info(f"📝 Monitoring gateway log: {gateway_log}")
        
        try:
            with open(gateway_log, 'r') as f:
                # Go to end of file
                f.seek(0, 2)
                
                while self.running:
                    line = f.readline()
                    if line:
                        skill_name, data = self._parse_skill_data(line, gateway_log)
                        if skill_name and data:
                            self._on_skill_invoked(skill_name, data)
                    else:
                        time.sleep(0.1)
        except Exception as e:
            self.logger.error(f"❌ Error monitoring gateway: {e}")
    
    def start(self, filter_skill=None):
        """Start monitoring"""
        self.running = True
        self.filter_skill = filter_skill
        self.logger.info(f"🎯 Monitoring skills (filter: {filter_skill or 'all'})")
        
        threads = []
        
        # Monitor individual skill log files in skill_log_dir
        skill_dir = Path(self.config["skill_log_dir"])
        if skill_dir.exists():
            self.logger.info(f"🔍 Scanning for skill logs in: {skill_dir}")
            skill_files = list(skill_dir.glob("*_skill.log"))
            
            if skill_files:
                self.logger.info(f"📋 Found {len(skill_files)} skill log files")
                for logfile in skill_files:
                    skill_name = logfile.stem.replace("_skill", "")
                    self.logger.info(f"✅ Adding file monitor: {skill_name} ({logfile.name})")
                    t = threading.Thread(
                        target=self._monitor_file, 
                        args=(str(logfile), skill_name), 
                        daemon=True
                    )
                    t.start()
                    threads.append(t)
            else:
                self.logger.info("📋 No skill log files found in skill_log_dir")
        else:
            self.logger.warning(f"⚠️ Skill log directory not found: {skill_dir}")
        
        # Monitor gateway log
        self.logger.info("✅ Adding gateway log monitor")
        t = threading.Thread(target=self._monitor_gateway, daemon=True)
        t.start()
        threads.append(t)
        
        self.logger.info(f"🎯 Monitoring active with {len(threads)} threads")
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def stop(self):
        """Stop monitoring"""
        self.running = False
        self.logger.info("⏹️  Monitoring stopped")
        self._export_stats()
    
    def _export_stats(self):
        """Export statistics to JSON file"""
        export_file = Path(self.config["output_dir"]) / f"stats_{datetime.now():%Y%m%d_%H%M%S}.json"
        with open(export_file, 'w') as f:
            json.dump(dict(self.stats), f, indent=2, ensure_ascii=False)
        self.logger.info(f"📊 Stats exported to: {export_file}")
    
    def get_stats(self):
        """Get current statistics"""
        return dict(self.stats)


def main():
    parser = argparse.ArgumentParser(description="OpenClaw Skill Monitor")
    parser.add_argument("--skill", "-s", help="Filter by skill name")
    parser.add_argument("--export", "-e", choices=["json", "csv"], help="Export format")
    parser.add_argument("--dashboard", "-d", action="store_true", help="Start web dashboard")
    parser.add_argument("--config", "-c", help="Custom config file path")
    args = parser.parse_args()
    
    # Default config path
    if not args.config:
        script_dir = Path(__file__).parent
        config_path = script_dir / "config.json"
        if config_path.exists():
            args.config = str(config_path)
    
    monitor = SkillMonitor(args.config)
    
    # ============ Dashboard Mode / 仪表盘模式 ============
    if args.dashboard:
        from http.server import HTTPServer, SimpleHTTPRequestHandler
        
        # Base directory for dashboard files
        BASE_DIR = Path(__file__).parent
        
        class DashboardHandler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(BASE_DIR), **kwargs)
            
            def do_GET(self):
                # API endpoint: return JSON stats
                if self.path == "/api/stats":
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    stats = monitor.get_stats()
                    
                    # Save to file for external access
                    stats_file = Path(monitor.config["output_dir"]) / "current_stats.json"
                    stats_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(stats_file, 'w') as f:
                        json.dump(stats, f, indent=2)
                    
                    self.wfile.write(json.dumps(stats).encode())
                    return
                
                # Root path redirects to dashboard.html
                if self.path == "/" or self.path == "/index.html":
                    self.path = "/dashboard.html"
                
                # Serve static files
                return super().do_GET()
            
            def log_message(self, format, *args):
                # Quiet logging
                pass
        
        # Start dashboard server
        port = monitor.config["dashboard"]["port"]
        server = HTTPServer(("0.0.0.0", port), DashboardHandler)  # Changed to 0.0.0.0 for external access
        print(f"\n🌐 Dashboard: http://0.0.0.0:{port}")
        print(f"   Local access: http://localhost:{port}")
        print(f"   Remote access: http://<your-server-ip>:{port}")
        print(f"📄 Serving files from: {BASE_DIR}")
        
        # Auto-open browser if enabled
        if monitor.config["dashboard"]["auto_open"]:
            try:
                webbrowser.open(f"http://localhost:{port}")
            except:
                pass
        
        # Start monitoring in background thread
        print("\n🚀 Starting skill monitor in background...")
        threading.Thread(target=monitor.start, args=(args.skill,), daemon=True).start()
        
        print(f"\n✅ Dashboard running. Press Ctrl+C to stop.\n")
        
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n\n⏹️  Shutting down...")
            monitor.stop()
            server.shutdown()
    
    # ============ CLI Mode / 命令行模式 ============
    else:
        try:
            monitor.start(args.skill)
        except KeyboardInterrupt:
            monitor.stop()
        
        # Export if requested
        if args.export:
            stats = monitor.get_stats()
            outfile = f"skill_stats_{datetime.now():%Y%m%d_%H%M%S}.{args.export}"
            
            if args.export == "json":
                with open(outfile, 'w') as f:
                    json.dump(stats, f, indent=2, ensure_ascii=False)
            else:  # csv
                import csv
                with open(outfile, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["skill", "call_count", "last_call", "sample_param"])
                    for skill, data in stats.items():
                        writer.writerow([
                            skill, 
                            data["count"], 
                            data["last_call"], 
                            data["params"][-1] if data["params"] else "N/A"
                        ])
            print(f"✅ Exported to: {outfile}")


if __name__ == "__main__":
    main()
