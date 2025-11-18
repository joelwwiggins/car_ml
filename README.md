# OBD2 Vehicle Monitor with CNN Anomaly Detection

Real-time OBD2 data collection and monitoring system optimized for Raspberry Pi Zero 2W (512MB RAM). Uses Convolutional Neural Network autoencoder for anomaly detection and provides a web dashboard via Prometheus.

## Features

- 🚗 **OBD2 Data Collection**: Engine temperature, RPM, speed, fuel level
- 🤖 **AI Anomaly Detection**: CNN autoencoder-based outlier detection on time-series sensor data
- 📊 **Real-time Dashboard**: Web interface with live metrics
- 🐳 **Docker Optimized**: Lightweight containers for RPi Zero 2W
- 🔋 **Low Voltage Protection**: Automatic shutdown on battery drain
- 📈 **Prometheus Metrics**: Industry-standard monitoring
- 🔄 **Robust Recovery**: Checkpoint saving and error recovery
- 📝 **Comprehensive Logging**: System and application logs

## Architecture

```
┌─────────────────┐    ┌──────────────────┐
│   OBD2 Collector │    │  Prometheus +    │
│   (Data + CNN)   │◄──►│   Dashboard      │
│                 │    │                  │
│ • CAN bus data  │    │ • Web UI         │
│ • Anomaly scores │    │ • Metrics API    │
│ • Prometheus exp │    │ • Grafana-ready  │
└─────────────────┘    └──────────────────┘
         ▲                        ▲
         └─────────┬──────────────┘
                   │
            ┌─────────────────┐
            │   CAN HAT /     │
            │   Serial OBD2   │
            │   Interface     │
            └─────────────────┘
```

## Hardware Requirements

- **Raspberry Pi Zero 2W** (512MB RAM)
- **CAN HAT**: PiCAN or Waveshare CAN HAT (MCP2515-based)
- **ADC Module**: ADS1015 for battery voltage monitoring
- **OBD2 Interface**: Standard OBD2-to-DB9 cable
- **Power Supply**: Stable 5V/2A with battery monitoring circuit

### Hardware Wiring

#### CAN HAT Connection
- Connect CAN HAT to RPi GPIO pins
- CAN H/L lines to OBD2 cable
- 120Ω termination resistor (if not on HAT)

#### Voltage Monitoring Circuit
```
Battery +12V → Voltage Divider (10kΩ + 10kΩ) → ADS1015 A0
RPi I2C: SDA (GPIO 2), SCL (GPIO 3), GND, 3.3V
```

### Voltage Divider Calculation
- R1 = R2 = 10kΩ (half voltage)
- ADC reads 0-3.3V representing 0-6.6V battery
- Scale factor: `adc_voltage * 2`

## Quick Start

### 1. Desktop Development Setup

```bash
# Clone and setup venv
git clone <your-repo>
cd car_ml
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Test locally (mock data)
python3 obd2_collector.py
```

### 2. RPi Deployment

```bash
# On Raspberry Pi Zero 2W
git clone <your-repo>
cd car_ml
chmod +x setup_rpi.sh
sudo ./setup_rpi.sh

# Reboot to enable CAN interface
sudo reboot

# After reboot, start monitoring
sudo systemctl start obd2-monitor voltage-monitor
```

### 3. Desktop Build Process

```bash
# Setup Docker Buildx for ARM64 cross-compilation
./setup_buildx.sh

# Build optimized multi-stage images
./build_and_deploy.sh
```

### 3. Access Dashboard

- **Web Dashboard**: `http://<rpi-ip>:5000`
- **Prometheus**: `http://<rpi-ip>:9090`
- **Metrics API**: `http://<rpi-ip>:8000`

## Configuration

### OBD2 Settings (`obd2_config.json`)

```json
{
  "can_interface": "can0",
  "can_bitrate": 500000,
  "prometheus_port": 8000,
  "data_buffer_size": 1000,
  "sequence_length": 50,
  "low_voltage_threshold": 11.5
}
```

### Prometheus (`prometheus.yml`)

Configured for local metrics collection with 1-second intervals.

## Docker Deployment

### Multi-Stage Build Optimization

The Dockerfiles use multi-stage builds to minimize final image size and optimize for ARM64:

**Data Collector (`Dockerfile.data`):**
- **Builder Stage**: Compiles Python dependencies with build tools
- **Runtime Stage**: Minimal Debian with only essential libraries
- **Result**: ~150MB image (down from ~300MB single-stage)

**Monitor (`Dockerfile.monitor`):**
- **Prometheus Builder**: Downloads and extracts ARM64 Prometheus
- **Python Builder**: Creates virtual environment with dependencies
- **Runtime Stage**: Combines both with minimal base image
- **Result**: ~200MB image with full monitoring stack

### Build for RPi (ARM64)

```bash
# Setup Buildx for cross-compilation
./setup_buildx.sh

# Build data collector
docker buildx build \
    --platform linux/arm64 \
    -f Dockerfile.data \
    -t obd2-collector:arm64 \
    --load .

# Build monitoring dashboard
docker buildx build \
    --platform linux/arm64 \
    -f Dockerfile.monitor \
    -t obd2-monitor:arm64 \
    --load .

# Deploy with docker-compose
docker-compose up -d
```

### Platform Architecture

- **Raspberry Pi Zero 2W**: ARM64 (aarch64)
- **Base Images**: `arm64v8/python:3.11-slim-bookworm`
- **Prometheus**: `prometheus-2.45.0.linux-arm64.tar.gz`

## CAN Bus Setup

### Hardware Connection

1. Connect CAN HAT to RPi GPIO
2. Connect OBD2 cable to vehicle
3. Power on system

### Software Setup

```bash
# Enable CAN interface
sudo ip link set can0 up type can bitrate 500000

# Check status
ip link show can0
```

## Anomaly Detection

### CNN Autoencoder Model

- **Architecture**: 1D Convolutional Autoencoder with encoder-decoder structure
- **Input**: Time sequences of 50 samples × 4 sensor features
- **Training**: Automatic after collecting sufficient normal operation data
- **Features**: Engine temp, RPM, speed, fuel level
- **Anomaly Score**: Reconstruction error (MSE between input and output)
- **Threshold**: Score > 0.6 = warning, > 0.8 = critical

### Real-time Scoring

- Updates every data collection cycle
- Normalized anomaly score (0-1) based on reconstruction error
- Dashboard shows real-time status

## Monitoring & Logging

### Logs

- **Application**: `/app/logs/obd2_collector.log`
- **System**: `journalctl -u obd2-monitor`
- **Docker**: `docker-compose logs`

### Health Checks

- **Collector**: HTTP endpoint `/health`
- **Monitor**: Prometheus `/healthy`
- **Dashboard**: Flask `/health`

### Metrics

- `obd2_engine_temperature`
- `obd2_engine_rpm`
- `obd2_vehicle_speed`
- `obd2_fuel_level`
- `obd2_battery_voltage`
- `obd2_anomaly_score`
- `obd2_data_points_total`
- `obd2_errors_total`

## Low Voltage Protection

### Automatic Shutdown System

The system includes dual voltage monitoring:

1. **In-Container Monitoring**: OBD2 collector checks voltage every second
2. **System-Level Monitoring**: Independent `voltage_monitor.py` service

### Shutdown Logic

- **Threshold**: 11.0V (configurable)
- **Grace Period**: 60 seconds of sustained low voltage
- **Action**: Graceful container shutdown → System halt

### Hardware Setup

```bash
# Enable I2C for ADS1015
sudo raspi-config nonint do_i2c 0

# Install ADC libraries
pip3 install adafruit-circuitpython-ads1x15 adafruit-blinka
```

### Service Management

```bash
# Start voltage monitor
sudo systemctl start voltage-monitor

# Check status
sudo systemctl status voltage-monitor

# View logs
journalctl -u voltage-monitor
```

## Troubleshooting

### Common Issues

1. **CAN Interface Not Found**
   ```bash
   # Check kernel modules
   lsmod | grep can
   # Load modules
   sudo modprobe can
   sudo modprobe can_raw
   ```

2. **Memory Issues**
   ```bash
   # Monitor memory usage
   docker stats
   # Check system memory
   free -h
   ```

3. **OBD2 No Response**
   ```bash
   # Test CAN communication
   cansend can0 7DF#0201050000000000
   candump can0
   ```

### Recovery

- **Checkpoint Restore**: Automatic on restart
- **Log Analysis**: Check `/app/logs/` for errors
- **Container Restart**: `docker-compose restart`

## Development

### Local Testing

```bash
# Mock CAN interface for testing
python3 -c "
import obd2_collector
# Test with mock data
"
```

### Adding New Sensors

1. Add PID mapping in `obd2_collector.py`
2. Update Prometheus metrics
3. Add to dashboard display

## Performance

### RPi Zero 2W Benchmarks

- **Startup Time**: 8-12 seconds
- **Memory Usage**: ~400MB total (CNN model + data buffer)
- **Data Collection**: 1Hz
- **Anomaly Detection**: <200ms per cycle (includes sequence processing)

### Optimization Features

- Lightweight Python base image
- Minimal dependencies
- Efficient GMM implementation
- Circular buffer for data storage

## Security

- Non-root container execution
- Minimal attack surface
- Local network access only
- No external dependencies

## License

MIT License - see LICENSE file for details.
