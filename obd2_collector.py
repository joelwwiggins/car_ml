#!/usr/bin/env python3
"""
OBD2 Data Collector with GMM Anomaly Detection for Raspberry Pi Zero 2W
Optimized for 512MB RAM with lightweight processing and robust error handling.
"""

import time
import logging
import signal
import sys
import os
from collections import deque
from typing import Dict, List, Optional, Tuple
import threading
import json

# CAN and OBD2 libraries
import can
import serial
from prometheus_client import start_http_server, Gauge, Counter, Histogram

# ML libraries for GMM
import numpy as np
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

# Configuration
CAN_INTERFACE = 'can0'
CAN_BITRATE = 500000
PROMETHEUS_PORT = 8000
DATA_BUFFER_SIZE = 100
LOG_FILE = os.path.join(os.path.dirname(__file__), 'logs', 'obd2_collector.log')
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config', 'obd2_config.json')

# Prometheus metrics
obd2_temperature = Gauge('obd2_engine_temperature', 'Engine coolant temperature (°C)')
obd2_rpm = Gauge('obd2_engine_rpm', 'Engine RPM')
obd2_speed = Gauge('obd2_vehicle_speed', 'Vehicle speed (km/h)')
obd2_fuel_level = Gauge('obd2_fuel_level', 'Fuel level (%)')
obd2_voltage = Gauge('obd2_battery_voltage', 'Battery voltage (V)')
obd2_anomaly_score = Gauge('obd2_anomaly_score', 'GMM anomaly detection score (0-1)')
obd2_error_count = Counter('obd2_errors_total', 'Total OBD2 communication errors')
obd2_data_points = Counter('obd2_data_points_total', 'Total data points collected')

class OBD2Collector:
    def __init__(self):
        self.logger = self._setup_logging()
        self.data_buffer = deque(maxlen=DATA_BUFFER_SIZE)
        self.gmm_model = None
        self.scaler = StandardScaler()
        self.is_training = True
        self.training_samples = 0
        self.min_training_samples = 100
        self.shutdown_event = threading.Event()
        self.mock_mode = False  # Add mock mode flag

        # OBD2 PID mappings (simplified)
        self.pid_mappings = {
            0x05: ('engine_temp', obd2_temperature),
            0x0C: ('engine_rpm', obd2_rpm),
            0x0D: ('vehicle_speed', obd2_speed),
            0x2F: ('fuel_level', obd2_fuel_level),
        }

        # Low voltage shutdown threshold
        self.low_voltage_threshold = 11.5  # Volts

        # CAN bus setup
        self.bus = None
        self.serial_conn = None

        self.logger.info("OBD2 Collector initialized")

    def _setup_logging(self) -> logging.Logger:
        """Setup comprehensive logging for debugging and monitoring."""
        logger = logging.getLogger('obd2_collector')
        logger.setLevel(logging.INFO)

        # Create logs directory if it doesn't exist
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

        # File handler
        file_handler = logging.FileHandler(LOG_FILE)
        file_handler.setLevel(logging.INFO)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger

    def setup_can_interface(self) -> bool:
        """Setup CAN interface for OBD2 communication."""
        try:
            # Try CAN bus first
            self.bus = can.interface.Bus(channel=CAN_INTERFACE, bustype='socketcan', bitrate=CAN_BITRATE)
            self.logger.info(f"CAN interface {CAN_INTERFACE} initialized")
            return True
        except Exception as e:
            self.logger.warning(f"CAN interface failed: {e}, trying serial fallback")

        try:
            # Fallback to serial (for some OBD2 adapters)
            self.serial_conn = serial.Serial('/dev/ttyUSB0', 38400, timeout=1)
            self.logger.info("Serial OBD2 adapter initialized")
            return True
        except Exception as e:
            self.logger.warning(f"Serial interface failed: {e}, running in MOCK mode")
            self.mock_mode = True
            return True

    def send_obd2_request(self, pid: int) -> Optional[bytes]:
        """Send OBD2 PID request and return response."""
        if self.mock_mode:
            # Generate mock OBD2 response data
            import random
            if pid == 0x05:  # Engine coolant temperature (70-110°C)
                temp = random.randint(70, 110)
                return bytes([0x03, 0x41, 0x05, temp + 40, 0x00, 0x00, 0x00])
            elif pid == 0x0C:  # Engine RPM (800-4000)
                rpm = random.randint(800, 4000)
                rpm_a = rpm // 256
                rpm_b = rpm % 256
                return bytes([0x04, 0x41, 0x0C, rpm_a, rpm_b, 0x00, 0x00, 0x00])
            elif pid == 0x0D:  # Vehicle speed (0-120 km/h)
                speed = random.randint(0, 120)
                return bytes([0x03, 0x41, 0x0D, speed, 0x00, 0x00, 0x00, 0x00])
            elif pid == 0x2F:  # Fuel level (10-100%)
                fuel = random.randint(10, 100)
                fuel_scaled = int((fuel * 255) / 100)
                return bytes([0x03, 0x41, 0x2F, fuel_scaled, 0x00, 0x00, 0x00, 0x00])
            return None

        if self.bus:
            # CAN bus implementation
            try:
                # OBD2 request format: ID 0x7DF, data: [0x02, 0x01, PID, 0x00, 0x00, 0x00, 0x00, 0x00]
                request = can.Message(
                    arbitration_id=0x7DF,
                    data=[0x02, 0x01, pid, 0x00, 0x00, 0x00, 0x00, 0x00],
                    is_extended_id=False
                )
                self.bus.send(request)

                # Wait for response
                response = self.bus.recv(timeout=1.0)
                if response and response.arbitration_id == 0x7E8:
                    return response.data
            except Exception as e:
                self.logger.error(f"CAN request failed: {e}")
                obd2_error_count.inc()

        elif self.serial_conn:
            # Serial implementation (ELM327 protocol)
            try:
                cmd = f"01{pid:02X}\r"
                self.serial_conn.write(cmd.encode())
                time.sleep(0.1)
                response = self.serial_conn.read(100)
                return response
            except Exception as e:
                self.logger.error(f"Serial request failed: {e}")
                obd2_error_count.inc()

        return None

    def parse_obd2_response(self, pid: int, data: bytes) -> Optional[float]:
        """Parse OBD2 response data into readable values."""
        try:
            if len(data) < 3:
                return None

            # Skip header bytes and get actual data
            # For single byte responses: data[3] contains the value
            # For multi-byte responses: data[3] and data[4] contain the values
            if pid in [0x05, 0x0D, 0x2F]:  # Single byte PIDs
                value_byte = data[3]
            elif pid == 0x0C:  # Two byte PID (RPM)
                if len(data) >= 5:
                    return ((data[3] * 256) + data[4]) / 4  # Formula: ((A*256)+B)/4

            # Convert based on PID
            if pid == 0x05:  # Engine coolant temperature
                return value_byte - 40  # Formula: A - 40
            elif pid == 0x0D:  # Vehicle speed
                return value_byte  # Formula: A (km/h)
            elif pid == 0x2F:  # Fuel level
                return (value_byte * 100) / 255  # Formula: (A*100)/255 (%)

        except Exception as e:
            self.logger.error(f"Failed to parse OBD2 data: {e}")

        return None

    def collect_data_point(self) -> Dict:
        """Collect one complete data point from all sensors."""
        data_point = {}
        timestamp = time.time()

        for pid, (name, metric) in self.pid_mappings.items():
            response = self.send_obd2_request(pid)
            if response:
                value = self.parse_obd2_response(pid, response)
                if value is not None:
                    data_point[name] = value
                    metric.set(value)

        # Add battery voltage (if available via separate monitoring)
        # This would need additional hardware/circuit
        data_point['timestamp'] = timestamp
        data_point['battery_voltage'] = self.check_battery_voltage()

        return data_point

    def check_battery_voltage(self) -> float:
        """Check battery voltage for low voltage shutdown using ADC."""
        try:
            # Try to read from ADS1015 ADC via I2C
            import board
            import busio
            import adafruit_ads1x15.ads1015 as ADS
            from adafruit_ads1x15.analog_in import AnalogIn

            # Initialize I2C bus and ADC
            i2c = busio.I2C(board.SCL, board.SDA)
            ads = ADS.ADS1015(i2c)
            chan = AnalogIn(ads, ADS.P0)  # A0 pin

            # Voltage divider: assuming 10k/10k divider (half voltage)
            # ADC reading * 2 * reference voltage / max ADC value
            voltage = chan.voltage * 2 * 3.3 / 2047.0

            self.logger.debug(f"ADC voltage reading: {chan.voltage:.3f}V, calculated battery: {voltage:.1f}V")
            obd2_voltage.set(voltage)
            return voltage

        except (ImportError, AttributeError):
            self.logger.warning("ADS1015 libraries not available or board pins not configured, using mock voltage")
            # Fallback to mock value for development/testing
            voltage = 12.5
            obd2_voltage.set(voltage)
            return voltage
        except Exception as e:
            self.logger.error(f"Failed to read battery voltage: {e}")
            # Return safe default
            voltage = 12.0
            obd2_voltage.set(voltage)
            return voltage

    def update_gmm_model(self, data_point: Dict):
        """Update GMM model with new data point."""
        # Extract features for GMM (exclude timestamp and battery voltage)
        features = [v for k, v in data_point.items()
                   if k not in ['timestamp', 'battery_voltage'] and isinstance(v, (int, float))]

        if len(features) < 2:
            return

        # Add to buffer
        self.data_buffer.append(features)

        # Convert to numpy array for training
        if len(self.data_buffer) >= self.min_training_samples:
            X = np.array(list(self.data_buffer))

            if self.is_training:
                # Initial training
                self.scaler.fit(X)
                X_scaled = self.scaler.transform(X)

                self.gmm_model = GaussianMixture(n_components=2, random_state=42)
                self.gmm_model.fit(X_scaled)

                self.is_training = False
                self.logger.info("GMM model trained with initial data")

            else:
                # Update existing model (simplified - in practice you'd retrain periodically)
                X_scaled = self.scaler.transform(X)
                scores = self.gmm_model.score_samples(X_scaled)

                # Anomaly score is negative log likelihood (higher = more anomalous)
                current_score = -scores[-1]  # Most recent point
                normalized_score = min(current_score / 10.0, 1.0)  # Normalize to 0-1
                obd2_anomaly_score.set(normalized_score)

    def check_low_voltage_shutdown(self, voltage: float):
        """Check if voltage is low enough to trigger shutdown."""
        if voltage < self.low_voltage_threshold:
            self.logger.warning(f"Low voltage detected: {voltage}V, initiating shutdown")
            self.shutdown_event.set()

    def save_checkpoint(self):
        """Save current model state for recovery."""
        try:
            checkpoint = {
                'data_buffer': list(self.data_buffer),
                'training_samples': self.training_samples,
                'is_training': self.is_training,
                'scaler_mean': self.scaler.mean_.tolist() if hasattr(self.scaler, 'mean_') else None,
                'scaler_scale': self.scaler.scale_.tolist() if hasattr(self.scaler, 'scale_') else None,
            }

            with open(os.path.join(os.path.dirname(__file__), 'checkpoint.json'), 'w') as f:
                json.dump(checkpoint, f)

        except Exception as e:
            self.logger.error(f"Failed to save checkpoint: {e}")

    def load_checkpoint(self):
        """Load previous model state."""
        try:
            if os.path.exists(os.path.join(os.path.dirname(__file__), 'checkpoint.json')):
                with open(os.path.join(os.path.dirname(__file__), 'checkpoint.json'), 'r') as f:
                    checkpoint = json.load(f)

                self.data_buffer.extend(checkpoint.get('data_buffer', []))
                self.training_samples = checkpoint.get('training_samples', 0)
                self.is_training = checkpoint.get('is_training', True)

                if checkpoint.get('scaler_mean') and checkpoint.get('scaler_scale'):
                    self.scaler.mean_ = np.array(checkpoint['scaler_mean'])
                    self.scaler.scale_ = np.array(checkpoint['scaler_scale'])

                # If we have enough data, retrain the model
                if len(self.data_buffer) >= self.min_training_samples:
                    X = np.array(list(self.data_buffer))
                    X_scaled = self.scaler.transform(X)
                    self.gmm_model = GaussianMixture(n_components=2, random_state=42)
                    self.gmm_model.fit(X_scaled)
                    self.is_training = False
                    self.logger.info("GMM model retrained from checkpoint data")
                else:
                    self.is_training = True

                self.logger.info("Checkpoint loaded successfully")

        except Exception as e:
            self.logger.error(f"Failed to load checkpoint: {e}")

    def run(self):
        """Main collection loop."""
        self.logger.info("Starting OBD2 data collection")

        if not self.setup_can_interface():
            self.logger.error("Failed to setup OBD2 interface, exiting")
            return

        # Load previous state
        self.load_checkpoint()

        # Start Prometheus metrics server
        start_http_server(PROMETHEUS_PORT)
        self.logger.info(f"Prometheus metrics server started on port {PROMETHEUS_PORT}")

        collection_interval = 1.0  # 1 second intervals

        try:
            while not self.shutdown_event.is_set():
                start_time = time.time()

                # Collect data
                data_point = self.collect_data_point()

                if data_point:
                    # Update metrics
                    obd2_data_points.inc()

                    # Update GMM model
                    self.update_gmm_model(data_point)

                    # Check for low voltage
                    voltage = data_point.get('battery_voltage', 12.0)
                    self.check_low_voltage_shutdown(voltage)

                    self.logger.info(f"Data point collected: {data_point}")

                # Periodic checkpoint save
                if int(time.time()) % 300 == 0:  # Every 5 minutes
                    self.save_checkpoint()

                # Maintain collection interval
                elapsed = time.time() - start_time
                sleep_time = max(0, collection_interval - elapsed)
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            self.logger.info("Received interrupt signal")
        except Exception as e:
            self.logger.error(f"Unexpected error in main loop: {e}")
        finally:
            self.cleanup()

    def cleanup(self):
        """Cleanup resources."""
        self.logger.info("Cleaning up resources")

        if self.bus:
            self.bus.shutdown()

        if self.serial_conn:
            self.serial_conn.close()

        self.save_checkpoint()
        self.logger.info("OBD2 Collector shutdown complete")

def signal_handler(signum, frame):
    """Handle shutdown signals."""
    logger = logging.getLogger('obd2_collector')
    logger.info(f"Received signal {signum}, initiating shutdown")
    collector.shutdown_event.set()

if __name__ == "__main__":
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    collector = OBD2Collector()
    collector.run()