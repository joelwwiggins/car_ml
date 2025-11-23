#!/bin/bash
# Build and Deploy OBD2 Monitor for Raspberry Pi Zero 2W
# Run this on your desktop development machine

set -e

echo "🚗 Building OBD2 Monitor for Raspberry Pi Zero 2W..."

# Enable Docker buildx for cross-compilation
docker buildx create --use --name cross-builder 2>/dev/null || docker buildx use cross-builder

# Build car-ml container (ARM64)
echo "Building car-ml container..."
docker buildx build \
    --platform linux/arm64 \
    --file Dockerfile \
    --tag car-ml:arm64 \
    --load \
    .

# Build monitoring container (ARM64)
# echo "Building monitoring container..."
# docker buildx build \
#     --platform linux/arm64 \
#     --file Dockerfile \
#     --tag car-ml:arm64 \
#     --load \
#     .

echo "✅ Container built successfully!"
echo ""
echo "📦 Deployment Options:"
echo ""
echo "Option 1 - Save to tar file for transfer:"
echo "docker save car-ml:arm64 > car-ml-arm64.tar"
echo "scp car-ml-arm64.tar pi@<rpi-ip>:/home/pi/"
echo "ssh pi@<rpi-ip> 'docker load < car-ml-arm64.tar'"
echo ""
echo "Option 2 - Push to registry (requires registry access):"
echo "docker tag car-ml:arm64 your-registry/car-ml:arm64"
echo "docker push your-registry/car-ml:arm64"
echo ""
echo "Option 3 - Direct deploy (if RPi accessible via SSH):"
echo "scp -r . pi@<rpi-ip>:/home/pi/car_ml"
echo "ssh pi@<rpi-ip> 'cd /home/pi/car_ml && docker-compose up -d'"
echo ""
echo "🎯 Memory Usage (optimized for 512MB RPi Zero 2W):"
echo "- OBD2 Collector + Dashboard: ~200-256MB"
echo "- Total: <300MB with overhead"
echo ""
echo "🔧 Hardware Requirements:"
echo "- Raspberry Pi Zero 2W"
echo "- CAN HAT (MCP2515-based)"
echo "- ADS1015 ADC for voltage monitoring"
echo "- OBD2 cable"
echo ""
echo "📊 Access Points:"
echo "- Web Dashboard: http://<rpi-ip>:5000"
echo "- Historical Data API: http://<rpi-ip>:5000/history"