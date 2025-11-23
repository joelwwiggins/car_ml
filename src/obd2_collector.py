#!/usr/bin/env python3
"""
Lean OBD2 Collector with CNN Anomaly Detection for Raspberry Pi Zero 2W
Integrated voltage monitoring, SQLite storage, and Flask WebSocket dashboard
"""

import time
import sys
import os
import signal
from collections import deque
import threading
import json
import sqlite3
import subprocess

# CAN and OBD2
import can
import serial

# ML for anomaly detection
import numpy as np
try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    try:
        import tensorflow.lite as tflite
    except ImportError:
        tflite = None

# Flask and WebSockets
from flask import Flask, render_template_string, jsonify
from flask_socketio import SocketIO, emit
import eventlet
eventlet.monkey_patch()

# Voltage monitoring
ADC_AVAILABLE = False
try:
    import board
    import busio
    import adafruit_ads1x15.ads1015 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn
    ADC_AVAILABLE = True
except ImportError:
    pass

# Configuration
CAN_INTERFACE = 'can0'
CAN_BITRATE = 500000
FLASK_PORT = 5000
SEQUENCE_LENGTH = 32
FEATURE_DIM = 12  # 12 PIDs
BUFFER_SIZE = 100
COLLECTION_INTERVAL = 0.5  # 2 Hz
VOLTAGE_THRESHOLD = 11.0
VOLTAGE_GRACE_PERIOD = 60  # seconds
DB_PATH = '/data/obd2_data.db'

# Flask app
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Global db_conn
db_conn = None

class SimpleScaler:
    def __init__(self):
        self.mean = None
        self.scale = None

    def fit(self, data):
        data = np.array(data)
        self.mean = np.mean(data, axis=0)
        self.scale = np.std(data, axis=0)
        # Avoid division by zero
        self.scale[self.scale == 0] = 1.0

    def transform(self, data):
        if self.mean is None or self.scale is None:
            return np.array(data)
        return (np.array(data) - self.mean) / self.scale

class OBD2Collector:
    def __init__(self):
        self.bus = None
        self.serial_conn = None
        self.interpreter = None
        self.scaler = SimpleScaler()
        self.data_buffer = deque(maxlen=BUFFER_SIZE)
        self.is_trained = False
        self.shutdown_event = threading.Event()
        self.low_voltage_start = None
        self.db_conn = None

        # OBD2 PIDs (12 total)
        self.pids = {
            0x04: 'calc_load',
            0x05: 'engine_temp',
            0x06: 'short_fuel_trim',
            0x07: 'long_fuel_trim',
            0x0B: 'intake_pressure',
            0x0C: 'engine_rpm',
            0x0D: 'vehicle_speed',
            0x0E: 'timing_advance',
            0x0F: 'intake_temp',
            0x10: 'mass_air_flow',
            0x11: 'throttle_pos',
            0x2F: 'fuel_level',
        }

        # Setup ADC for voltage
        self.adc_chan = None
        if ADC_AVAILABLE:
            try:
                i2c = busio.I2C(board.SCL, board.SDA)
                ads = ADS.ADS1015(i2c)
                self.adc_chan = AnalogIn(ads, ADS.P0)
            except:
                self.adc_chan = None

        self.load_model()
        self.setup_database()

    def setup_database(self):
        """Setup SQLite database."""
        global db_conn
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        db_conn = self.db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.db_conn.execute('''
            CREATE TABLE IF NOT EXISTS obd2_data (
                timestamp REAL PRIMARY KEY,
                engine_temp REAL,
                engine_rpm REAL,
                vehicle_speed REAL,
                fuel_level REAL,
                mass_air_flow REAL,
                intake_temp REAL,
                throttle_pos REAL,
                calc_load REAL,
                short_fuel_trim REAL,
                long_fuel_trim REAL,
                timing_advance REAL,
                intake_pressure REAL,
                battery_voltage REAL,
                anomaly_score REAL
            )
        ''')
        self.db_conn.commit()

    def load_model(self):
        """Load INT8 quantized TFLite model."""
        model_path = os.path.join(os.path.dirname(__file__), '..', 'models/cnn_model_int8.tflite')
        if os.path.exists(model_path) and tflite is not None:
            self.interpreter = tflite.Interpreter(model_path=model_path)
            self.interpreter.allocate_tensors()
            print("TFLite model loaded")
        else:
            print("Warning: TFLite model not found or runtime missing, running without anomaly detection")

    def setup_interfaces(self):
        """Setup CAN or serial interfaces."""
        try:
            self.bus = can.interface.Bus(channel=CAN_INTERFACE, bustype='socketcan', bitrate=CAN_BITRATE)
            print("CAN interface ready")
            return True
        except:
            pass

        try:
            self.serial_conn = serial.Serial('/dev/ttyUSB0', 38400, timeout=1)
            print("Serial interface ready")
            return True
        except:
            pass

        print("No OBD2 interface available, running in mock mode")
        return True

    def send_obd2_request(self, pid):
        """Send OBD2 request via CAN or serial."""
        if self.bus:
            try:
                request = can.Message(arbitration_id=0x7DF, data=[0x02, 0x01, pid, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False)
                self.bus.send(request)
                response = self.bus.recv(timeout=1.0)
                if response and response.arbitration_id == 0x7E8:
                    return response.data
            except:
                pass
        elif self.serial_conn:
            try:
                self.serial_conn.write(f"01{pid:02X}\r".encode())
                time.sleep(0.1)
                response_line = self.serial_conn.readline().decode().strip()
                if response_line and "41" in response_line:
                    parts = response_line.split()
                    if len(parts) >= 3 and parts[0] == "41" and int(parts[1], 16) == pid:
                        data = bytes([0x41, pid] + [int(x, 16) for x in parts[2:]])
                        return data
            except:
                pass
        return None

    def parse_obd2_response(self, pid, data):
        """Parse OBD2 response data."""
        if not data or len(data) < 3:
            return None

        if pid in [0x04, 0x05, 0x06, 0x07, 0x0B, 0x0D, 0x0E, 0x0F, 0x11, 0x2F]:
            value = data[3] if len(data) > 3 else 0
        elif pid in [0x0C, 0x10]:
            if len(data) >= 5:
                value = (data[3] * 256 + data[4])
            else:
                return None

        # Convert based on PID formula
        if pid == 0x04: return (value * 100) / 255  # Calculated load
        elif pid == 0x05: return value - 40  # Engine temp
        elif pid == 0x06: return (value - 128) * 100 / 128  # Short fuel trim
        elif pid == 0x07: return (value - 128) * 100 / 128  # Long fuel trim
        elif pid == 0x0B: return value  # Intake pressure
        elif pid == 0x0C: return value / 4  # RPM
        elif pid == 0x0D: return value  # Speed
        elif pid == 0x0E: return (value / 2) - 64  # Timing advance
        elif pid == 0x0F: return value - 40  # Intake temp
        elif pid == 0x10: return value / 100  # MAF
        elif pid == 0x11: return (value * 100) / 255  # Throttle
        elif pid == 0x2F: return (value * 100) / 255  # Fuel level
        return None

    def collect_data_point(self):
        """Collect data from all PIDs."""
        data_point = {}
        for pid, name in self.pids.items():
            response = self.send_obd2_request(pid)
            if response:
                value = self.parse_obd2_response(pid, response)
                if value is not None:
                    data_point[name] = value

        # Add battery voltage
        voltage = self.read_voltage()
        data_point['battery_voltage'] = voltage

        return data_point

    def store_data_point(self, data_point):
        """Store data point in SQLite database."""
        if self.db_conn:
            timestamp = time.time()
            self.db_conn.execute('''
                INSERT OR REPLACE INTO obd2_data (
                    timestamp, engine_temp, engine_rpm, vehicle_speed, fuel_level,
                    mass_air_flow, intake_temp, throttle_pos, calc_load,
                    short_fuel_trim, long_fuel_trim, timing_advance,
                    intake_pressure, battery_voltage, anomaly_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                timestamp,
                data_point.get('engine_temp'),
                data_point.get('engine_rpm'),
                data_point.get('vehicle_speed'),
                data_point.get('fuel_level'),
                data_point.get('mass_air_flow'),
                data_point.get('intake_temp'),
                data_point.get('throttle_pos'),
                data_point.get('calc_load'),
                data_point.get('short_fuel_trim'),
                data_point.get('long_fuel_trim'),
                data_point.get('timing_advance'),
                data_point.get('intake_pressure'),
                data_point.get('battery_voltage'),
                data_point.get('anomaly_score', 0)
            ))
            self.db_conn.commit()

    def read_voltage(self):
        """Read battery voltage from ADC."""
        if self.adc_chan:
            try:
                return self.adc_chan.voltage * 2 * 3.3 / 2047.0
            except:
                pass
        return 12.5  # Mock voltage

    def compute_anomaly_score(self):
        """Compute anomaly score using TFLite model."""
        if not self.interpreter or len(self.data_buffer) < SEQUENCE_LENGTH:
            return 0.0

        # Get recent sequence
        recent = np.array(list(self.data_buffer)[-SEQUENCE_LENGTH:])
        scaled = self.scaler.transform(recent) if self.is_trained else recent

        # Prepare input
        input_data = scaled.reshape(1, SEQUENCE_LENGTH, FEATURE_DIM).astype(np.float32)
        input_details = self.interpreter.get_input_details()
        output_details = self.interpreter.get_output_details()

        # Quantize input if needed
        if input_details[0]['dtype'] == np.int8:
            input_scale, input_zero_point = input_details[0]['quantization']
            input_data = (input_data / input_scale + input_zero_point).astype(np.int8)

        self.interpreter.set_tensor(input_details[0]['index'], input_data)
        self.interpreter.invoke()
        output_data = self.interpreter.get_tensor(output_details[0]['index'])

        # Dequantize output if needed
        if output_details[0]['dtype'] == np.int8:
            output_scale, output_zero_point = output_details[0]['quantization']
            output_data = (output_data.astype(np.float32) - output_zero_point) * output_scale

        # Compute MSE
        mse = np.mean(np.square(scaled - output_data.squeeze()))
        score = min(mse * 10, 1.0)  # Scale for sensitivity
        return score

    def check_voltage_shutdown(self, voltage):
        """Check for low voltage shutdown."""
        if voltage < VOLTAGE_THRESHOLD:
            if self.low_voltage_start is None:
                self.low_voltage_start = time.time()
                print(f"Low voltage detected: {voltage:.1f}V")
            elif time.time() - self.low_voltage_start > VOLTAGE_GRACE_PERIOD:
                print("Low voltage timeout, shutting down")
                self.shutdown()
        else:
            self.low_voltage_start = None

    def shutdown(self):
        """Shutdown system."""
        try:
            subprocess.run(['sudo', 'shutdown', '-h', 'now'], check=True)
        except:
            os._exit(0)

    def run(self):
        """Main collection loop."""
        if not self.setup_interfaces():
            return

        # Start Flask server in background thread
        flask_thread = threading.Thread(target=lambda: socketio.run(app, host='0.0.0.0', port=FLASK_PORT))
        flask_thread.daemon = True
        flask_thread.start()
        print(f"Flask dashboard on port {FLASK_PORT}")

        # Train scaler on initial data
        print("Collecting initial data for normalization...")
        initial_samples = []
        for _ in range(SEQUENCE_LENGTH):
            data = self.collect_data_point()
            if data:
                features = [data.get(name, 0) for name in self.pids.values()]
                initial_samples.append(features)
                time.sleep(COLLECTION_INTERVAL)
        if initial_samples:
            self.scaler.fit(initial_samples)
            self.is_trained = True
            print("Normalization ready")

        print("Starting main collection loop")
        while not self.shutdown_event.is_set():
            start_time = time.time()

            data_point = self.collect_data_point()
            if data_point:
                # Store in database
                self.store_data_point(data_point)

                features = [data_point.get(name, 0) for name in self.pids.values()]
                self.data_buffer.append(features)

                # Compute anomaly score
                score = self.compute_anomaly_score()
                data_point['anomaly_score'] = score

                # Store updated data point with anomaly score
                self.store_data_point(data_point)

                # Emit to WebSocket clients
                socketio.emit('obd2_data', data_point)

                # Check voltage
                self.check_voltage_shutdown(data_point['battery_voltage'])

            # Maintain interval
            elapsed = time.time() - start_time
            sleep_time = max(0, COLLECTION_INTERVAL - elapsed)
            time.sleep(sleep_time)

    def cleanup(self):
        """Cleanup resources."""
        if self.bus:
            self.bus.shutdown()
        if self.serial_conn:
            self.serial_conn.close()
        if self.db_conn:
            self.db_conn.close()

# Flask routes
@app.route('/')
def dashboard():
    return render_template_string(DASHBOARD_HTML)

@app.route('/history')
def history():
    global db_conn
    if db_conn:
        rows = db_conn.execute('''
            SELECT * FROM obd2_data ORDER BY timestamp DESC LIMIT 100
        ''').fetchall()
        # Convert to dict
        data = []
        for row in rows:
            data.append({
                'timestamp': row[0],
                'engine_temp': row[1],
                'engine_rpm': row[2],
                'vehicle_speed': row[3],
                'fuel_level': row[4],
                'mass_air_flow': row[5],
                'intake_temp': row[6],
                'throttle_pos': row[7],
                'calc_load': row[8],
                'short_fuel_trim': row[9],
                'long_fuel_trim': row[10],
                'timing_advance': row[11],
                'intake_pressure': row[12],
                'battery_voltage': row[13],
                'anomaly_score': row[14]
            })
        return jsonify({'data': data})
    return jsonify({'data': []})

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>OBD2 Dashboard</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .metric { display: inline-block; margin: 10px; padding: 10px; border: 1px solid #ccc; border-radius: 5px; }
        .value { font-size: 24px; font-weight: bold; }
        .label { font-size: 12px; color: #666; }
        .anomaly { color: red; }
        .chart-container { width: 800px; height: 400px; margin: 20px 0; }
    </style>
</head>
<body>
    <h1>OBD2 Real-time Dashboard</h1>
    <div id="metrics"></div>
    <h2>Historical Data (Last 100 points)</h2>
    <div class="chart-container">
        <canvas id="historyChart"></canvas>
    </div>
    <script>
        const socket = io();
        const metricsDiv = document.getElementById('metrics');
        let historyData = [];

        // Fetch historical data
        fetch('/history').then(r => r.json()).then(data => {
            historyData = data.data.reverse(); // oldest first
            updateChart();
        });

        socket.on('obd2_data', function(data) {
            metricsDiv.innerHTML = '';
            Object.keys(data).forEach(key => {
                const div = document.createElement('div');
                div.className = 'metric';
                div.innerHTML = `
                    <div class="label">${key.replace(/_/g, ' ').toUpperCase()}</div>
                    <div class="value ${key === 'anomaly_score' && data[key] > 0.5 ? 'anomaly' : ''}">${data[key] ? data[key].toFixed(2) : 'N/A'}</div>
                `;
                metricsDiv.appendChild(div);
            });

            // Add to history and update chart
            historyData.push(data);
            if (historyData.length > 100) historyData.shift();
            updateChart();
        });

        function updateChart() {
            const ctx = document.getElementById('historyChart').getContext('2d');
            const labels = historyData.map(d => new Date(d.timestamp * 1000).toLocaleTimeString());
            const rpmData = historyData.map(d => d.engine_rpm || 0);
            const anomalyData = historyData.map(d => d.anomaly_score || 0);

            new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Engine RPM',
                        data: rpmData,
                        borderColor: 'blue',
                        fill: false
                    }, {
                        label: 'Anomaly Score',
                        data: anomalyData,
                        borderColor: 'red',
                        fill: false,
                        yAxisID: 'y1'
                    }]
                },
                options: {
                    scales: {
                        y: {
                            type: 'linear',
                            display: true,
                            position: 'left',
                        },
                        y1: {
                            type: 'linear',
                            display: true,
                            position: 'right',
                            grid: {
                                drawOnChartArea: false,
                            },
                        }
                    }
                }
            });
        }
    </script>
</body>
</html>
"""

def signal_handler(signum, frame):
    collector.shutdown_event.set()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    collector = OBD2Collector()
    try:
        collector.run()
    finally:
        collector.cleanup()