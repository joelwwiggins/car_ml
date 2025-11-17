#!/bin/bash
# RPi OBD2 Setup Script
# Configures CAN bus interface and system settings for OBD2 monitoring

set -e

echo "🚗 Setting up RPi for OBD2 monitoring..."

# Update system
echo "Updating system packages..."
sudo apt-get update && sudo apt-get upgrade -y

# Install required packages
echo "Installing required packages..."
sudo apt-get install -y \
    can-utils \
    iproute2 \
    net-tools \
    python3-dev \
    build-essential \
    libatlas-base-dev \
    docker.io \
    docker-compose \
    git

# Enable SPI and I2C (for some CAN HATs)
echo "Enabling SPI and I2C interfaces..."
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0

# Setup CAN interface (adjust for your specific CAN HAT)
echo "Setting up CAN interface..."
# For MCP2515 based CAN HATs (common on RPi)
sudo sh -c 'echo "dtparam=spi=on" >> /boot/config.txt'
sudo sh -c 'echo "dtoverlay=mcp2515-can0,oscillator=16000000,interrupt=25,spimaxfrequency=1000000" >> /boot/config.txt'

# Create CAN interface configuration
sudo sh -c 'cat > /etc/network/interfaces.d/can0 << EOF
auto can0
iface can0 can static
    bitrate 500000
    restart-ms 1000
EOF'

# Enable and start CAN interface
echo "Enabling CAN interface..."
sudo systemctl enable systemd-networkd
sudo systemctl start systemd-networkd

# Setup Docker
echo "Setting up Docker..."
sudo systemctl enable docker
sudo systemctl start docker

# Add user to docker group (optional, for development)
sudo usermod -aG docker $USER

# Create application directories
echo "Creating application directories..."
mkdir -p ~/obd2_monitor/logs
mkdir -p ~/obd2_monitor/config
mkdir -p ~/obd2_monitor/prometheus_data

# Clone or copy application code
echo "Setting up application code..."
# Assuming code is already there, or you can clone from repo
cd ~/obd2_monitor

# Setup log rotation
echo "Setting up log rotation..."
sudo sh -c 'cat > /etc/logrotate.d/obd2_monitor << EOF
/app/logs/*.log {
    daily
    missingok
    rotate 7
    compress
    notifempty
    create 644 root root
}
EOF'

# Setup systemd service for auto-start
echo "Setting up systemd service..."
sudo sh -c 'cat > /etc/systemd/system/obd2-monitor.service << EOF
[Unit]
Description=OBD2 Vehicle Monitor
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/home/pi/obd2_monitor
ExecStart=/usr/bin/docker-compose up
ExecStop=/usr/bin/docker-compose down
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF'

sudo systemctl daemon-reload
sudo systemctl enable obd2-monitor.service

# Setup watchdog for low voltage shutdown
echo "Setting up low voltage monitoring..."
sudo sh -c 'cat > /usr/local/bin/check_voltage.sh << '"'"'EOF'"'"'
#!/bin/bash
# Check battery voltage and shutdown if too low
# This requires ADC hardware connected to battery

VOLTAGE=$(python3 -c "
import time
# Mock voltage check - replace with actual ADC reading
voltage = 12.5
print(voltage)
")

THRESHOLD=11.5

if (( $(echo "$VOLTAGE < $THRESHOLD" | bc -l) )); then
    echo "$(date): Low voltage detected: ${VOLTAGE}V, shutting down" >> /var/log/obd2_voltage.log
    /usr/bin/docker-compose -f /home/pi/obd2_monitor/docker-compose.yml down
    sudo shutdown -h now
fi
EOF'

sudo chmod +x /usr/local/bin/check_voltage.sh

# Add to cron for periodic checking
echo "*/5 * * * * /usr/local/bin/check_voltage.sh" | sudo crontab -

# Setup firewall (optional)
echo "Setting up firewall..."
sudo apt-get install -y ufw
sudo ufw allow 9090/tcp  # Prometheus
sudo ufw allow 5000/tcp  # Dashboard
sudo ufw --force enable

echo "🎉 RPi OBD2 setup complete!"
echo ""
echo "Next steps:"
echo "1. Reboot the RPi: sudo reboot"
echo "2. After reboot, check CAN interface: ip link show can0"
echo "3. Bring up CAN interface: sudo ip link set can0 up"
echo "4. Start the monitoring system: sudo systemctl start obd2-monitor"
echo "5. Access dashboard at: http://<rpi-ip>:5000"
echo ""
echo "For troubleshooting:"
echo "- Check logs: docker-compose logs"
echo "- CAN interface: dmesg | grep can"
echo "- System logs: journalctl -u obd2-monitor"