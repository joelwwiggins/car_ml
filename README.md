# Lean OBD2 Collector with CNN Anomaly Detection

Ultra-lightweight OBD2 data collection and multivariate anomaly detection optimized for Raspberry Pi Zero 2W (512MB RAM). Single-container deployment with TFLite inference and Prometheus metrics export.

## Features

- 🚗 **OBD2 Data Collection**: 12 PIDs including engine sensors, fuel system, and timing
- 🤖 **TFLite Anomaly Detection**: INT8-quantized CNN autoencoder for efficient inference
- 📊 **Prometheus Export**: Direct metrics exposure for external monitoring
- 🔋 **Battery Protection**: ADC-based voltage monitoring with safe shutdown
- � **Single Container**: ≤180MB Docker image optimized for ARM64
- ⚡ **Low Resource**: <200MB runtime memory on Pi Zero 2W

## Architecture

```
┌─────────────────┐
│   OBD2 Collector │
│ • CAN/Serial I/O │
│ • Data buffering │
│ • Normalization  │
│ • TFLite CNN     │
│ • Anomaly score  │
│ • Prometheus /metrics │
│ • Voltage check  │
└─────────────────┘
         ▲
         │
    ┌────────────┐
    │ CAN/Serial │
    │ OBD2 + ADC │
    └────────────┘
```

## Quick Start

### 1. Setup and Build

```bash
# Clone repository
git clone https://github.com/joelwwiggins/car_ml.git
cd car_ml

# Quantize existing model (if you have cnn_model.h5)
python3 quantize_model.py

# Build optimized Docker image
docker buildx build --platform linux/arm64 -f docker/Dockerfile -t obd2-collector:latest .
```

### 2. Deploy on Raspberry Pi Zero 2W

```bash
# Copy to Pi and run
docker-compose up -d

# Check metrics
curl http://localhost:8000/metrics
```

### 3. Monitor

Point Prometheus to `http://<pi-ip>:8000` for metrics collection.

## Configuration

### Environment Variables

- `PYTHONUNBUFFERED=1` (required for Docker logging)

### Hardware Setup

- **CAN Interface**: `can0` at 500k bitrate
- **Serial Fallback**: `/dev/ttyUSB0` for ELM327 adapters
- **ADC**: ADS1015 on I2C for voltage monitoring

## Performance

- **Image Size**: ≤180MB
- **Runtime Memory**: ≤200MB peak
- **Collection Rate**: 2Hz (500ms intervals)
- **Inference Time**: <50ms per sequence
- **Startup Time**: <10 seconds

## Metrics

- `obd2_engine_temperature` - Engine coolant temp (°C)
- `obd2_engine_rpm` - Engine RPM
- `obd2_vehicle_speed` - Speed (km/h)
- `obd2_fuel_level` - Fuel level (%)
- `obd2_mass_air_flow` - MAF (g/s)
- `obd2_intake_air_temp` - Intake temp (°C)
- `obd2_throttle_position` - Throttle (%)
- `obd2_calculated_load` - Calculated load (%)
- `obd2_short_fuel_trim` - Short term fuel trim (%)
- `obd2_long_fuel_trim` - Long term fuel trim (%)
- `obd2_timing_advance` - Timing advance (°)
- `obd2_intake_manifold_pressure` - Intake pressure (kPa)
- `obd2_battery_voltage` - Battery voltage (V)
- `obd2_anomaly_score` - Anomaly score (0-1)
- `obd2_data_points_total` - Data points collected
- `obd2_errors_total` - Communication errors
