import os
import json
import argparse
from dotenv import load_dotenv

def mask_password(password, show_first=2, show_last=2):
    """Mask password showing first and last characters"""
    if not password:
        return ""

    length = len(password)

    # For very short passwords, show all asterisks
    if length <= show_first + show_last:
        return "*" * length

    first_part = password[:show_first]
    last_part = password[-show_last:]
    middle = "*" * (length - show_first - show_last)

    return first_part + middle + last_part

def load_config():
    # Load from .env first (for sensitive data)
    load_dotenv()
    
    # Command line args override everything
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="Path to JSON config file")
    parser.add_argument("--smtp-server")
    parser.add_argument("--smtp-port", type=int)
    parser.add_argument("--user")
    parser.add_argument("--pass")
    parser.add_argument("--to", action="append")
    args = parser.parse_args()
    
    # Start with defaults
    config = {
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 465,
        "user": None,
        "pass": None,
        "to": ["yzc526@163.com"]
    }
    
    # Load from JSON if specified
    if args.config:
        with open(args.config) as f:
            file_config = json.load(f)
            config.update(file_config)
    
    # Override with environment variables
    env_mapping = {
        "smtp_server": os.getenv("SMTP_SERVER"),
        "smtp_port": os.getenv("SMTP_PORT"),
        "user": os.getenv("EMAIL_USER"),
        "pass": os.getenv("EMAIL_PASS"),
    }
    for key, value in env_mapping.items():
        if value:
            if key == "smtp_port":
                config[key] = int(value)
            else:
                config[key] = value
    
    # Override with command line args
    if args.smtp_server:
        config["smtp_server"] = args.smtp_server
    if args.smtp_port:
        config["smtp_port"] = args.smtp_port
    if args.user:
        config["user"] = args.user
    if getattr(args, "pass", None):
        config["pass"] = getattr(args, "pass")
    if args.to:
        config["to"] = args.to
    
    # Validate
    if not config["user"] or not config["pass"]:
        raise ValueError("User and password must be provided")
    
    # Convert port to int if it's a string
    config["smtp_port"] = int(config["smtp_port"])
    
    return config

# Usage
config = load_config()

SMTP_SERVER = config["smtp_server"]
SMTP_PORT = config["smtp_port"]
USER = config["user"]
PASS = config["pass"]
FROM = config.get("from", USER)
TO = config["to"]  # Already a list

print(f"📧 Email configuration:")
print(f"  • SMTP: {SMTP_SERVER}:{SMTP_PORT}")
print(f"  • USER: {USER}")
#print(f"  • PASS: {'*' * len(PASS)}")  # Mask password for security
print(f"  • PASS: {mask_password(PASS, show_first=2, show_last=2)}")
print(f"  • TO: {', '.join(TO)}")
