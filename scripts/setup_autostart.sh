#!/bin/bash

# Determine the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
# The docker directory is a sibling of scripts/ or inside the project root
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DOCKER_DIR="$PROJECT_ROOT/docker"

SERVICE_NAME="car-ml"

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (sudo ./scripts/setup_autostart.sh)"
    exit 1
fi

# Get the user who invoked sudo, or current user
if [ -n "$SUDO_USER" ]; then
    REAL_USER="$SUDO_USER"
else
    REAL_USER="$(whoami)"
fi

echo "Configuring service for User: $REAL_USER"
echo "Docker Directory: $DOCKER_DIR"

# Create systemd service file
cat > /etc/systemd/system/$SERVICE_NAME.service <<EOF
[Unit]
Description=Car ML Docker Compose Service
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$DOCKER_DIR
User=$REAL_USER
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# Try 'docker compose' (v2) first
ExecStart=/usr/bin/docker compose up -d --remove-orphans
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable $SERVICE_NAME.service
systemctl restart $SERVICE_NAME.service

echo "Service installed. Status:"
systemctl status $SERVICE_NAME --no-pager
