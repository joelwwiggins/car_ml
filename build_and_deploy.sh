#!/bin/bash
# Build and Deploy OBD2 Monitor for Raspberry Pi Zero 2W
# Run this on your desktop development machine

set -e

echo "🚗 Building OBD2 Monitor for Raspberry Pi Zero 2W..."

# Enable Docker buildx for cross-compilation
docker buildx create --use --name cross-builder 2>/dev/null || docker buildx use cross-builder

# Build data collector container (ARM64)
echo "Building data collector container..."
docker buildx build \
    --platform linux/arm64 \
    --file Dockerfile.data \
    --tag obd2-collector:arm64 \
    --load \
    .

# Build monitoring container (ARM64)
echo "Building monitoring container..."
docker buildx build \
    --platform linux/arm64 \
    --file Dockerfile.monitor \
    --tag obd2-monitor:arm64 \
    --load \
    .

echo "✅ Containers built successfully!"
echo ""
echo "📦 Deployment Options:"
echo ""
echo "Option 1 - Save to tar files for transfer:"
echo "docker save obd2-collector:arm64 > obd2-collector-arm64.tar"
echo "docker save obd2-monitor:arm64 > obd2-monitor-arm64.tar"
echo "scp *.tar pi@<rpi-ip>:/home/pi/"
echo ""
echo "Option 2 - Push to registry (requires registry access):"
echo "# docker tag obd2-collector:arm64 your-registry/obd2-collector:arm64"
echo "# docker tag obd2-monitor:arm64 your-registry/obd2-monitor:arm64"
echo "# docker push your-registry/obd2-collector:arm64"
echo "# docker push your-registry/obd2-monitor:arm64"
echo ""
echo "Option 3 - Direct deploy (if RPi accessible via SSH):"
echo "# scp -r . pi@<rpi-ip>:/home/pi/obd2_monitor"
echo "# ssh pi@<rpi-ip> 'cd /home/pi/obd2_monitor && ./setup_rpi.sh'"
echo ""
echo "🎯 Memory Usage (optimized for 512MB RPi Zero 2W):"
echo "- Data Collector: ~100-200MB"
echo "- Monitor/Dashboard: ~75-150MB"
echo "- Total: <350MB with overhead"
echo ""
echo "🔧 Hardware Requirements:"
echo "- Raspberry Pi Zero 2W"
echo "- CAN HAT (MCP2515-based)"
echo "- ADS1015 ADC for voltage monitoring"
echo "- OBD2 cable"
echo ""
echo "📊 Access Points:"
echo "- Web Dashboard: http://<rpi-ip>:5000"
echo "- Prometheus: http://<rpi-ip>:9090"
echo "- Metrics API: http://<rpi-ip>:8000"