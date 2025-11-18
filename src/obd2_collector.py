#!/usr/bin/env python3
"""
OBD2 Data Collector with CNN Anomaly Detection for Raspberry Pi Zero 2W
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

# ML libraries for CNN anomaly detection
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models
from tensorflow import lite as tflite
from sklearn.preprocessing import StandardScaler

# Configuration
CAN_INTERFACE = 'can0'
CAN_BITRATE = 500000
PROMETHEUS_PORT = 8000
DATA_BUFFER_SIZE = 500  # Reduced for memory optimization
SEQUENCE_LENGTH = 32    # Reduced sequence length for memory efficiency
FEATURE_DIM = 7         # Number of sensor features
LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'obd2_collector.log')
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'obd2_config.json')

# Prometheus metrics
obd2_temperature = Gauge('obd2_engine_temperature', 'Engine coolant temperature (°C)')
obd2_rpm = Gauge('obd2_engine_rpm', 'Engine RPM')
obd2_speed = Gauge('obd2_vehicle_speed', 'Vehicle speed (km/h)')
obd2_fuel_level = Gauge('obd2_fuel_level', 'Fuel level (%)')
obd2_maf = Gauge('obd2_mass_air_flow', 'Mass air flow (g/s)')
obd2_intake_temp = Gauge('obd2_intake_air_temp', 'Intake air temperature (°C)')
obd2_throttle_pos = Gauge('obd2_throttle_position', 'Throttle position (%)')
obd2_voltage = Gauge('obd2_battery_voltage', 'Battery voltage (V)')
obd2_anomaly_score = Gauge('obd2_anomaly_score', 'CNN autoencoder anomaly detection score (0-1)')
obd2_error_count = Counter('obd2_errors_total', 'Total OBD2 communication errors')
obd2_data_points = Counter('obd2_data_points_total', 'Total data points collected')

class OBD2Collector:
    def __init__(self):
        self.logger = self._setup_logging()
        self.data_buffer = deque(maxlen=DATA_BUFFER_SIZE)
        self.cnn_model = None
        self.tflite_interpreter = None
        self.scaler = StandardScaler()
        self.is_training = True
        self.training_samples = 0
        self.min_training_samples = SEQUENCE_LENGTH  # Need sequence length for training
        self.shutdown_event = threading.Event()
        self.mock_mode = False  # Add mock mode flag

        # OBD2 PID mappings (simplified)
        self.pid_mappings = {
            0x05: ('engine_temp', obd2_temperature),
            0x0C: ('engine_rpm', obd2_rpm),
            0x0D: ('vehicle_speed', obd2_speed),
            0x2F: ('fuel_level', obd2_fuel_level),
            0x10: ('mass_air_flow', obd2_maf),
            0x0F: ('intake_air_temp', obd2_intake_temp),
            0x11: ('throttle_position', obd2_throttle_pos),
        }

        # Low voltage shutdown threshold
        self.low_voltage_threshold = 11.5  # Volts

        # CAN bus setup
        self.bus = None
        self.serial_conn = None

        self.logger.info("OBD2 Collector initialized")

    def create_cnn_autoencoder(self):
        """Create 1D CNN autoencoder for anomaly detection."""
        input_shape = (SEQUENCE_LENGTH, FEATURE_DIM)

        # Encoder
        encoder_input = layers.Input(shape=input_shape)
        x = layers.Conv1D(32, 7, activation='relu', padding='same')(encoder_input)
        x = layers.MaxPooling1D(2)(x)
        x = layers.Conv1D(16, 5, activation='relu', padding='same')(x)
        x = layers.MaxPooling1D(2)(x)
        x = layers.Conv1D(8, 3, activation='relu', padding='same')(x)
        encoded = layers.MaxPooling1D(2)(x)

        # Decoder
        x = layers.Conv1D(8, 3, activation='relu', padding='same')(encoded)
        x = layers.UpSampling1D(2)(x)
        x = layers.Conv1D(16, 5, activation='relu', padding='same')(x)
        x = layers.UpSampling1D(2)(x)
        x = layers.Conv1D(32, 7, activation='relu', padding='same')(x)
        x = layers.UpSampling1D(2)(x)
        decoded = layers.Conv1D(FEATURE_DIM, 3, activation='linear', padding='same')(x)

        autoencoder = models.Model(encoder_input, decoded)
        autoencoder.compile(optimizer='adam', loss='mse')

        return autoencoder

    def representative_dataset_gen(self):
        """Generate representative dataset for TFLite quantization."""
        for _ in range(100):
            yield [np.random.rand(1, SEQUENCE_LENGTH, FEATURE_DIM).astype(np.float32)]

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
            elif pid == 0x10:  # Mass air flow (5-50 g/s)
                maf = random.randint(500, 5000)  # Scaled by 100
                maf_a = maf // 256
                maf_b = maf % 256
                return bytes([0x04, 0x41, 0x10, maf_a, maf_b, 0x00, 0x00, 0x00])
            elif pid == 0x0F:  # Intake air temp (20-40°C)
                temp = random.randint(20, 40)
                return bytes([0x03, 0x41, 0x0F, temp + 40, 0x00, 0x00, 0x00, 0x00])
            elif pid == 0x11:  # Throttle position (0-100%)
                throttle = random.randint(0, 100)
                throttle_scaled = int((throttle * 255) / 100)
                return bytes([0x03, 0x41, 0x11, throttle_scaled, 0x00, 0x00, 0x00, 0x00])
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
            if pid in [0x05, 0x0D, 0x2F, 0x0F, 0x11]:  # Single byte PIDs
                value_byte = data[3]
            elif pid in [0x0C, 0x10]:  # Two byte PIDs
                if len(data) >= 5:
                    value_byte = (data[3] * 256) + data[4]
                else:
                    return None

            # Convert based on PID
            if pid == 0x05:  # Engine coolant temperature
                return value_byte - 40  # Formula: A - 40
            elif pid == 0x0C:  # Engine RPM
                return value_byte / 4  # Formula: ((A*256)+B)/4
            elif pid == 0x0D:  # Vehicle speed
                return value_byte  # Formula: A (km/h)
            elif pid == 0x2F:  # Fuel level
                return (value_byte * 100) / 255  # Formula: (A*100)/255 (%)
            elif pid == 0x10:  # Mass air flow
                return value_byte / 100  # Formula: ((A*256)+B)/100
            elif pid == 0x0F:  # Intake air temperature
                return value_byte - 40  # Formula: A - 40
            elif pid == 0x11:  # Throttle position
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

    def update_cnn_model(self, data_point: Dict):
        """Update CNN autoencoder model with new data point."""
        # Extract features for CNN (exclude timestamp and battery voltage)
        features = [v for k, v in data_point.items()
                   if k not in ['timestamp', 'battery_voltage'] and isinstance(v, (int, float))]

        if len(features) != FEATURE_DIM:
            return

        # Add to buffer
        self.data_buffer.append(features)
        self.training_samples += 1

        # Convert to numpy array for training
        if len(self.data_buffer) >= self.min_training_samples:
            X = np.array(list(self.data_buffer))

            if self.is_training:
                # Initial training
                self.scaler.fit(X)
                X_scaled = self.scaler.transform(X)

                # Create sequences for CNN
                sequences = []
                for i in range(len(X_scaled) - SEQUENCE_LENGTH + 1):
                    seq = X_scaled[i:i + SEQUENCE_LENGTH]
                    sequences.append(seq)

                X_sequences = np.array(sequences)

                # Create and train CNN autoencoder
                self.cnn_model = self.create_cnn_autoencoder()
                self.cnn_model.fit(X_sequences, X_sequences,
                                 epochs=50, batch_size=16, verbose=0)

                # Convert to TFLite for efficient inference
                converter = tflite.TFLiteConverter.from_keras_model(self.cnn_model)
                converter.optimizations = [tf.lite.Optimize.DEFAULT]
                converter.representative_dataset = self.representative_dataset_gen
                tflite_model = converter.convert()

                self.tflite_model = tflite_model
                self.tflite_interpreter = tflite.Interpreter(model_content=tflite_model)
                self.tflite_interpreter.allocate_tensors()

                # Save TFLite model
                tflite_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cnn_model.tflite')
                with open(tflite_path, 'wb') as f:
                    f.write(tflite_model)

                self.is_training = False
                self.logger.info("CNN autoencoder trained and converted to TFLite")

            else:
                # Update existing model (retrain periodically)
                if self.training_samples % 1000 == 0:  # Retrain every 1000 samples
                    X_scaled = self.scaler.transform(X)

                    sequences = []
                    for i in range(len(X_scaled) - SEQUENCE_LENGTH + 1):
                        seq = X_scaled[i:i + SEQUENCE_LENGTH]
                        sequences.append(seq)

                    X_sequences = np.array(sequences)
                    self.cnn_model.fit(X_sequences, X_sequences,
                                     epochs=10, batch_size=16, verbose=0)

                    # Reconvert to TFLite after retraining
                    converter = tflite.TFLiteConverter.from_keras_model(self.cnn_model)
                    converter.optimizations = [tf.lite.Optimize.DEFAULT]
                    converter.representative_dataset = self.representative_dataset_gen
                    tflite_model = converter.convert()

                    self.tflite_model = tflite_model
                    self.tflite_interpreter = tflite.Interpreter(model_content=tflite_model)
                    self.tflite_interpreter.allocate_tensors()

                    # Save updated TFLite model
                    tflite_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cnn_model.tflite')
                    with open(tflite_path, 'wb') as f:
                        f.write(tflite_model)

                    self.logger.info("CNN autoencoder retrained and TFLite updated")

                # Compute anomaly score using latest sequence
                if len(self.data_buffer) >= SEQUENCE_LENGTH and self.tflite_interpreter is not None:
                    recent_data = np.array(list(self.data_buffer)[-SEQUENCE_LENGTH:])
                    recent_sequence = recent_data.reshape(1, SEQUENCE_LENGTH, FEATURE_DIM).astype(np.float32)

                    input_details = self.tflite_interpreter.get_input_details()
                    output_details = self.tflite_interpreter.get_output_details()

                    self.tflite_interpreter.set_tensor(input_details[0]['index'], recent_sequence)
                    self.tflite_interpreter.invoke()
                    reconstructed = self.tflite_interpreter.get_tensor(output_details[0]['index'])

                    reconstruction_error = np.mean(np.square(recent_sequence - reconstructed))

                    # Normalize anomaly score (0-1)
                    normalized_score = min(reconstruction_error * 100, 1.0)  # Scale factor may need tuning
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

            # Save model if it exists
            if self.cnn_model is not None:
                model_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cnn_model.h5')
                self.cnn_model.save(model_path)
                checkpoint['model_saved'] = True

            # Check if TFLite model exists
            tflite_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cnn_model.tflite')
            checkpoint['tflite_saved'] = os.path.exists(tflite_path)

            with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'checkpoint.json'), 'w') as f:
                json.dump(checkpoint, f)

        except Exception as e:
            self.logger.error(f"Failed to save checkpoint: {e}")

    def load_checkpoint(self):
        """Load previous model state."""
        try:
            checkpoint_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'checkpoint.json')
            if os.path.exists(checkpoint_path):
                with open(checkpoint_path, 'r') as f:
                    checkpoint = json.load(f)

                self.data_buffer.extend(checkpoint.get('data_buffer', []))
                self.training_samples = checkpoint.get('training_samples', 0)
                self.is_training = checkpoint.get('is_training', True)

                if checkpoint.get('scaler_mean') and checkpoint.get('scaler_scale'):
                    self.scaler.mean_ = np.array(checkpoint['scaler_mean'])
                    self.scaler.scale_ = np.array(checkpoint['scaler_scale'])

                # Load model if saved
                model_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cnn_model.h5')
                tflite_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cnn_model.tflite')
                if os.path.exists(tflite_path) and checkpoint.get('tflite_saved', False):
                    with open(tflite_path, 'rb') as f:
                        self.tflite_model = f.read()
                    self.tflite_interpreter = tflite.Interpreter(model_content=self.tflite_model)
                    self.tflite_interpreter.allocate_tensors()
                    self.is_training = False
                    self.logger.info("TFLite model loaded from checkpoint")
                elif os.path.exists(model_path) and checkpoint.get('model_saved', False):
                    self.cnn_model = tf.keras.models.load_model(model_path)
                    self.is_training = False
                    self.logger.info("Keras model loaded from checkpoint")
                elif len(self.data_buffer) >= self.min_training_samples:
                    # Retrain if no saved model but have data
                    X = np.array(list(self.data_buffer))
                    X_scaled = self.scaler.fit_transform(X) if not hasattr(self.scaler, 'mean_') else self.scaler.transform(X)

                    sequences = []
                    for i in range(len(X_scaled) - SEQUENCE_LENGTH + 1):
                        seq = X_scaled[i:i + SEQUENCE_LENGTH]
                        sequences.append(seq)

                    X_sequences = np.array(sequences)
                    self.cnn_model = self.create_cnn_autoencoder()
                    self.cnn_model.fit(X_sequences, X_sequences,
                                     epochs=50, batch_size=16, verbose=0)
                    self.is_training = False
                    self.logger.info("CNN model retrained from checkpoint data")
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

        collection_interval = 0.5  # 2 Hz intervals

        try:
            while not self.shutdown_event.is_set():
                start_time = time.time()

                # Collect data
                data_point = self.collect_data_point()

                if data_point:
                    # Update metrics
                    obd2_data_points.inc()

                    # Update CNN model
                    self.update_cnn_model(data_point)

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