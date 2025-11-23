#!/bin/bash
# Setup Docker Buildx for Cross-Compilation to ARM64
# Run this on your desktop development machine

set -e

echo "🔧 Setting up Docker Buildx for ARM64 cross-compilation..."

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker Desktop or Docker CLI first."
    exit 1
fi

# Check if Buildx is available
if ! docker buildx version &> /dev/null; then
    echo "❌ Docker Buildx is not available. Please update Docker to a recent version."
    exit 1
fi

echo "✅ Docker Buildx is available"

# Create and use buildx builder
echo "🏗️  Creating cross-platform builder..."
docker buildx create --use --name arm64-builder 2>/dev/null || docker buildx use arm64-builder

# Bootstrap the builder
echo "🔄 Bootstrapping builder..."
docker buildx inspect --bootstrap

# Verify builder is ready
echo "🔍 Verifying builder configuration..."
docker buildx inspect

echo "✅ Docker Buildx setup complete!"
echo ""
echo "🚀 You can now build ARM64 images for Raspberry Pi Zero 2W"
echo ""
echo "Example build commands:"
echo "docker buildx build --platform linux/arm64 -f Dockerfile -t car-ml:arm64 --load ."
echo ""
echo "Or run the automated build script:"
echo "./build_and_deploy.sh"