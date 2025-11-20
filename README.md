# Lean OBD2 Collector with CNN Anomaly Detection

Ultra-lightweight OBD2 data collection and multivariate anomaly detection optimized for Raspberry Pi Zero 2W (512MB RAM). Single-container deployment with TFLite inference and Prometheus metrics export.

## Features

- 🚗 **OBD2 Data Collection**: 12 PIDs including engine sensors, fuel system, and timing
- 🤖 **TFLite Anomaly Detection**: INT8-quantized CNN autoencoder for efficient inference
- 📊 **Prometheus Export**: Direct metrics exposure for external monitoring
- 🔋 **Battery Protection**: ADC-based voltage monitoring with safe shutdown
- 🐳 **Single Container**: ≤180MB Docker image optimized for ARM64
- ⚡ **Low Resource**: <200MB runtime memory on Pi Zero 2W

## Project Structure

```
car_ml/
├── README.md                    # This file
├── requirements.txt             # Development dependencies
├── requirements.prod.txt        # Production dependencies (minimal)
├── config/
│   ├── obd2_config.json         # OBD2 configuration
│   └── prometheus.yml           # Prometheus config (optional)
├── docker/
│   ├── Dockerfile               # Multi-stage build for ARM64
│   └── docker-compose.yml       # Container orchestration
├── models/
│   ├── cnn_model.keras          # Trained Keras model
│   └── cnn_model_int8.tflite    # Quantized TFLite model
├── scripts/
│   ├── build_and_deploy.sh      # Build and deploy script
│   ├── prepare_vcan_dataset.py  # VCAN data preparation
│   ├── setup_buildx.sh          # Docker buildx setup
│   └── setup_rpi.sh             # RPi setup script
└── src/
    ├── __init__.py
    ├── model.py                 # CNN autoencoder architecture
    ├── obd2_collector.py        # Main collector application
    └── training/
        ├── train_model.py       # Training script
        └── quantize_model.py    # Quantization script
```

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

### Prerequisites

- Python 3.12+
- Docker with buildx support
- Virtual environment (recommended)

### 1. Setup Development Environment

```bash
# Clone and setup
git clone <repo-url>
cd car_ml

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Capture Representative VCAN Data (Optional)

For production accuracy, capture real vehicle data:

```bash
# On Raspberry Pi with CAN interface
candump -L vcan0 > vcan_capture.log
```

Transfer `vcan_capture.log` to your development machine and prepare:

```bash
python scripts/prepare_vcan_dataset.py --log-file vcan_capture.log --output data/vcan_sequences.npz
```

### 3. Train the Model

```bash
# Train with synthetic data (default)
python src/training/train_model.py --epochs 40 --batch-size 32

# Or with real VCAN data
python src/training/train_model.py --vcan-data data/vcan_sequences.npz --epochs 40 --batch-size 32
```

This creates `models/cnn_model.keras` and weights file.

### 4. Quantize for Edge Deployment

```bash
python src/training/quantize_model.py
```

Creates `models/cnn_model_int8.tflite` (optimized for RPi).

### 5. Test Locally

```bash
# Run collector in mock mode (no hardware required)
python src/obd2_collector.py
```

Access metrics at `http://localhost:8000/metrics`.

### 6. Build and Deploy

```bash
# Build ARM64 image
docker buildx build --platform linux/arm64 -f docker/Dockerfile -t obd2-collector:latest .

# Deploy on Raspberry Pi
docker save obd2-collector:latest | ssh pi@<pi-ip> 'docker load'
ssh pi@<pi-ip> 'cd /app && docker-compose up -d'
```

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

## Development

### Running Tests

```bash
# Train with minimal epochs for quick testing
python src/training/train_model.py --epochs 1

# Test quantization
python src/training/quantize_model.py

# Run collector locally
python src/obd2_collector.py
```

### Docker Development

```bash
# Build for local testing (amd64)
docker build -t obd2-collector-dev -f docker/Dockerfile .

# Run with mock data
docker run --rm -p 8000:8000 obd2-collector-dev
```

## Troubleshooting

- **No CAN interface**: Collector falls back to serial or mock mode
- **Memory issues**: Monitor with `docker stats` or `htop`
- **Model not loading**: Ensure `models/cnn_model_int8.tflite` exists
- **ADC not working**: Check I2C with `i2cdetect -y 1`

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

## License

MIT License - see LICENSE file for details.
