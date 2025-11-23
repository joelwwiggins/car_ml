# Lean OBD2 Collector with CNN Anomaly Detection

Ultra-lightweight OBD2 data collection and multivariate anomaly detection optimized for Raspberry Pi Zero 2W (512MB RAM). Single-container deployment with TFLite inference, SQLite storage, and real-time Flask WebSocket dashboard.

## Features

- 🚗 **OBD2 Data Collection**: 12 PIDs including engine sensors, fuel system, and timing
- 🤖 **TFLite Anomaly Detection**: INT8-quantized CNN autoencoder for efficient inference
- � **SQLite Storage**: Persistent data storage with historical trends
- 🌐 **Flask WebSocket Dashboard**: Real-time monitoring with live charts
- 🔋 **Battery Protection**: ADC-based voltage monitoring with safe shutdown
- 🐳 **Single Container**: ≤256MB Docker image optimized for ARM64
- ⚡ **Low Resource**: <256MB runtime memory on Pi Zero 2W

## Project Structure

```
car_ml/
├── README.md                    # This file
├── requirements.txt             # Development dependencies
├── requirements.prod.txt        # Production dependencies (minimal)
├── config/
│   └── obd2_config.json         # OBD2 configuration
├── docker-compose.yml           # Container orchestration
├── Dockerfile                   # Multi-stage build for ARM64
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
│ • SQLite storage │
│ • Flask WebSocket│
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

Access dashboard at `http://localhost:5000`.

### 6. Build and Deploy

```bash
# Build ARM64 image
docker buildx build --platform linux/arm64 -f Dockerfile -t car-ml:latest .

# Deploy on Raspberry Pi
docker save car-ml:latest | ssh pi@<pi-ip> 'docker load'
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

- **Image Size**: ≤256MB
- **Runtime Memory**: ≤256MB peak
- **Collection Rate**: 2Hz (500ms intervals)
- **Inference Time**: <50ms per sequence
- **Startup Time**: <10 seconds

## Dashboard

The Flask application provides a real-time dashboard with:

- **Live Metrics**: Current values for all OBD2 parameters
- **Anomaly Detection**: Real-time anomaly scoring with visual alerts
- **Historical Charts**: Engine RPM and anomaly score trends (last 100 points)
- **WebSocket Updates**: Live data streaming without page refresh

Access at `http://your-pi:5000`

## Data Storage

All OBD2 data is stored in SQLite (`/data/obd2_data.db`) with:

- Timestamped entries for full historical tracking
- All 12 OBD2 PIDs plus anomaly scores
- Battery voltage monitoring
- REST API access at `/history` for external queries

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
docker build -t car-ml-dev -f Dockerfile .

# Run with mock data
docker run --rm -p 5000:5000 car-ml-dev
```

## Troubleshooting

- **No CAN interface**: Collector falls back to serial or mock mode
- **Memory issues**: Monitor with `docker stats` or `htop`
- **Model not loading**: Ensure `models/cnn_model_int8.tflite` exists
- **ADC not working**: Check I2C with `i2cdetect -y 1`
- **Dashboard not loading**: Check port 5000 is accessible

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

## License

MIT License - see LICENSE file for details.
