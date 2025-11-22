#!/bin/bash

# Define variables
SERVICE_NAME="car-ml"
WORKING_DIR="/home/joel/scripts/car_ml/docker"
USER="joel"

echo "Setting up $SERVICE_NAME systemd service..."

# Create systemd service file
sudo tee /etc/systemd/system/$SERVICE_NAME.service > /dev/null <<EOF
[Unit]
Description=Car ML Docker Compose Service
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$WORKING_DIR
User=$USER
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd daemon
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable $SERVICE_NAME.service

# Start the service immediately
# sudo systemctl start $SERVICE_NAME.service

echo "Service $SERVICE_NAME installed and enabled."
echo "You can start it with: sudo systemctl start $SERVICE_NAME"
