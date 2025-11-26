
import threading
import time
import queue
import sqlite3
import os
import can  # python-can library
import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
import plotly.graph_objs as go
import plotly.utils
import json
try:
    import systemd.daemon
    SYSTEMD_AVAILABLE = True
except ImportError:
    SYSTEMD_AVAILABLE = False
    print("Systemd not available, running without watchdog")

# Configuration
CAN_INTERFACE = 'can0'  # PiCAN3 interface
SAMPLE_RATE = 0.1  # 100 ms intervals
OBD_PIDS = [  # Standard Mode 01 PIDs (hex arbitration IDs)
    0x7DF,  # Request broadcast
    # Responses: e.g., 0x7E8 for RPM (0x0C), Speed (0x0D), Coolant (0x05), Throttle (0x11)
]
TRAIN_SAMPLES = 200  # Initial training batch size
ANOMALY_THRESHOLD = 2.0  # Std devs for anomaly detection
MODEL_COMPONENTS = 3  # GMM components (tune based on data)
VOLTAGE_PIN = 17  # GPIO pin for low voltage detection
LOW_VOLTAGE_THRESHOLD = 11.5  # Volts

# SQLite setup
DB_PATH = 'obd_data.db'
db_lock = threading.Lock()

def init_db():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute('''CREATE TABLE IF NOT EXISTS obd_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL,
            rpm REAL,
            speed REAL,
            coolant REAL,
            throttle REAL,
            anomaly INTEGER DEFAULT 0
        )''')
        conn.commit()
        conn.close()

init_db()

# Voltage monitoring thread
def voltage_monitor():
    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(VOLTAGE_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        while True:
            if GPIO.input(VOLTAGE_PIN) == GPIO.LOW:
                print("Low voltage detected, shutting down...")
                os.system('sudo shutdown now')
            time.sleep(1.0)
    except ImportError:
        print("RPi.GPIO not available, skipping voltage monitoring")
        while True:
            time.sleep(10)

# Watchdog ping thread
def watchdog_ping():
    while True:
        if SYSTEMD_AVAILABLE:
            systemd.daemon.notify('WATCHDOG=1')
        time.sleep(10)

# Global queues and state for threading
data_queue = queue.Queue(maxsize=1000)  # Buffer for collected data
model = None  # GMM instance

app = Flask(__name__)
app.config['SECRET_KEY'] = 'obd_dashboard_key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# OBD-II PID Request Function (simplified; extend for full ELM-like parsing)
def request_pid(arbitration_id, pid):
    if bus is None:
        return None  # Mock mode
    
    msg = can.Message(arbitration_id=arbitration_id, data=[0x02, 0x01, pid, 0, 0, 0, 0, 0], is_extended_id=False)
    bus.send(msg)
    response = bus.recv(timeout=0.05)  # Short timeout for performance
    if response and response.arbitration_id == 0x7E8:
        # Parse A/D bytes (simplified; assumes single value response)
        value = (response.data[3] * 256 + response.data[4]) / 256.0  # Example scaling for RPM
        return value
    return None

# Data Collection Thread
def collect_data():
    global bus
    try:
        bus = can.interface.Bus(channel=CAN_INTERFACE, interface='socketcan')
        bus.set_filters([{"can_id": 0x7E8, "can_mask": 0x7FF, "extended": False}])  # Filter OBD responses
        print("CAN interface initialized successfully")
    except OSError as e:
        print(f"CAN interface not available ({e}), running in mock mode")
        bus = None
    
    pids = {'rpm': 0x0C, 'speed': 0x0D, 'coolant': 0x05, 'throttle': 0x11}
    while True:
        timestamp = time.time()
        row = {'timestamp': timestamp}
        
        for key, pid in pids.items():
            if bus is not None:
                value = request_pid(0x7DF, pid)
                row[key] = value if value is not None else np.nan  # Handle missing data
            else:
                # Mock data for testing - occasionally generate anomalies
                import random
                is_anomaly = random.random() < 0.05  # 5% chance of anomaly
                
                if is_anomaly:
                    # Generate anomalous values
                    row[key] = {
                        'rpm': random.uniform(5000, 8000),  # Very high RPM
                        'speed': random.uniform(0, 200),    # Normal speed
                        'coolant': random.uniform(120, 150), # High coolant temp
                        'throttle': random.uniform(90, 100)  # High throttle
                    }[key]
                else:
                    # Normal values
                    row[key] = {
                        'rpm': random.uniform(800, 3000),
                        'speed': random.uniform(0, 120),
                        'coolant': random.uniform(70, 110),
                        'throttle': random.uniform(0, 100)
                    }[key]
        
        # Enqueue for modeling/dashboard
        if not data_queue.full():
            data_queue.put(row)
        
        # Insert into SQLite
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            conn.execute('INSERT INTO obd_data (timestamp, rpm, speed, coolant, throttle) VALUES (?, ?, ?, ?, ?)',
                         (row['timestamp'], row['rpm'], row['speed'], row['coolant'], row['throttle']))
            conn.commit()
            # Clean old data: keep last 500
            conn.execute('DELETE FROM obd_data WHERE id NOT IN (SELECT id FROM obd_data ORDER BY id DESC LIMIT 500)')
            conn.commit()
            conn.close()
        
        time.sleep(SAMPLE_RATE)

# Modeling Thread (Incremental GMM Fitting)
def model_anomalies():
    global model
    time.sleep(TRAIN_SAMPLES * SAMPLE_RATE)  # Wait for initial data
    
    while True:
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.execute('SELECT rpm, speed, coolant, throttle FROM obd_data ORDER BY id DESC LIMIT ?', (TRAIN_SAMPLES,))
            rows = cursor.fetchall()
            conn.close()
        
        if len(rows) >= TRAIN_SAMPLES:
            features = np.array(rows)
            # Handle NaN values by forward filling, then replace remaining NaN with 0
            features = pd.DataFrame(features, columns=['rpm', 'speed', 'coolant', 'throttle'])
            features = features.ffill().fillna(0).values
            
            # Fit or update model
            if model is None:
                model = GaussianMixture(n_components=MODEL_COMPONENTS, random_state=42)
                model.fit(features)
            else:
                # Refit with new data (not truly incremental, but better than nothing)
                model.fit(features)
            
            # Score latest batch (last 10)
            latest_features = features[-10:]
            scores = model.score_samples(latest_features)
            mean_score = np.mean(scores)
            std_score = np.std(scores)
            
            with db_lock:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.execute('SELECT id FROM obd_data ORDER BY id DESC LIMIT 10')
                ids = [row[0] for row in cursor.fetchall()]
                ids.reverse()  # To match latest_features order
                for i, (id_, score) in enumerate(zip(ids, scores)):
                    anomaly = 1 if abs(score - mean_score) > ANOMALY_THRESHOLD * std_score else 0
                    conn.execute('UPDATE obd_data SET anomaly = ? WHERE id = ?', (anomaly, id_))
                conn.commit()
                conn.close()
        
        time.sleep(5.0)  # Refit every 5 seconds

# Dashboard Routes
@app.route('/')
def dashboard():
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head><title>OBD-II Anomaly Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .metric { display: inline-block; margin: 10px; padding: 10px; border: 1px solid #ccc; border-radius: 5px; }
        .value { font-size: 18px; font-weight: bold; }
        .label { font-size: 12px; color: #666; }
        .anomaly { color: red; background-color: #ffe6e6; }
        .chart-container { width: 100%; height: 400px; margin: 20px 0; }
    </style>
    </head>
    <body>
    <h1>Ford F-250 OBD-II Monitoring</h1>
    <div id="live-data"></div>
    <div class="chart-container">
        <div id="rpm-chart"></div>
    </div>
    <div class="chart-container">
        <div id="anomaly-chart"></div>
    </div>
    <script>
        var socket = io();
        var rpmData = { x: [], y: [], mode: 'lines+markers', name: 'RPM' };
        var anomalyData = { x: [], y: [], mode: 'lines+markers', name: 'Anomaly Score', line: {color: 'red'} };
        
        socket.on('update', function(data) {
            // Update live metrics
            document.getElementById('live-data').innerHTML = '';
            ['rpm', 'speed', 'coolant', 'throttle'].forEach(function(key) {
                var div = document.createElement('div');
                div.className = 'metric' + (data.anomaly ? ' anomaly' : '');
                div.innerHTML = '<div class="label">' + key.toUpperCase() + '</div>' +
                               '<div class="value">' + (data[key] ? data[key].toFixed(1) : 'N/A') + '</div>';
                document.getElementById('live-data').appendChild(div);
            });
            
            // Add to chart data (keep last 50 points)
            var timestamp = new Date(data.timestamp * 1000);
            rpmData.x.push(timestamp);
            rpmData.y.push(data.rpm || 0);
            anomalyData.x.push(timestamp);
            anomalyData.y.push(data.anomaly ? 1 : 0);
            
            if (rpmData.x.length > 50) {
                rpmData.x.shift();
                rpmData.y.shift();
                anomalyData.x.shift();
                anomalyData.y.shift();
            }
            
            // Update charts
            Plotly.newPlot('rpm-chart', [rpmData], {title: 'Engine RPM Over Time'});
            Plotly.newPlot('anomaly-chart', [anomalyData], {title: 'Anomaly Detection'});
        });
    </script>
    </body>
    </html>
    ''')

# SocketIO Emitter Thread
def emit_updates():
    while True:
        if not data_queue.empty():
            row = data_queue.get()
            # Get latest anomaly from DB for this data point
            with db_lock:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.execute('SELECT anomaly FROM obd_data WHERE timestamp = ? ORDER BY id DESC LIMIT 1', (row['timestamp'],))
                result = cursor.fetchone()
                conn.close()
            row['anomaly'] = bool(result[0]) if result else False
            socketio.emit('update', row)
        time.sleep(0.1)  # Match sample rate

if __name__ == '__main__':
    # Start threads
    threading.Thread(target=voltage_monitor, daemon=True).start()
    threading.Thread(target=watchdog_ping, daemon=True).start()
    threading.Thread(target=collect_data, daemon=True).start()
    threading.Thread(target=model_anomalies, daemon=True).start()
    threading.Thread(target=emit_updates, daemon=True).start()
    
    # Run Flask app
    print("Starting Flask app on port 5000...")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)