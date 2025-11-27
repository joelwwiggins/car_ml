#!/usr/bin/env python3
import threading
import time
import queue
import sqlite3
import os
import can
import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture
from flask import Flask, render_template_string
from flask_socketio import SocketIO
import eventlet
eventlet.monkey_patch()

# === CRITICAL: PiCAN FD Zero Configuration ===
CAN_INTERFACE = 'can0'
CAN_BITRATE = 500000        # Arbitration phase: 500 kbit/s
CAN_DBITRATE = 2000000      # Data phase: 2 Mbit/s (CAN-FD)
CAN_FD_ENABLED = True
CAN_BRS_ENABLED = True      # Bit Rate Switch

# Rest of your configuration
SAMPLE_RATE = 0.1
TRAIN_SAMPLES = 200
ANOMALY_THRESHOLD = 2.5
MODEL_COMPONENTS = 3
DB_PATH = 'obd_data.db'
db_lock = threading.Lock()

# Initialize DB
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

# Global objects
data_queue = queue.Queue(maxsize=1000)
model = None
app = Flask(__name__)
app.config['SECRET_KEY'] = 'obd_f250_secure_key_2025'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# === CORRECT CAN BUS INITIALIZATION FOR MCP2518FD ===
def init_can_bus():
    try:
        bus = can.interface.Bus(
            channel=CAN_INTERFACE,
            bustype='socketcan',
            fd=CAN_FD_ENABLED,
            bitrate=CAN_BITRATE,
            data_bitrate=CAN_DBITRATE,
            brs=CAN_BRS_ENABLED,
            sample_point=0.8,
            dsample_point=0.8
        )
        print("CAN-FD interface can0 initialized successfully (500k/2M)")
        return bus
    except Exception as e:
        print(f"CAN interface failed ({e}), falling back to mock mode")
        return None

bus = init_can_bus()

# PID definitions with correct OBD-II scaling
PIDS = {
    'rpm':      (0x0C, lambda a, b: (a * 256 + b) / 4.0),
    'speed':    (0x0D, lambda a: a),
    'coolant':  (0x05, lambda a: a - 40),
    'throttle': (0x11, lambda a: a * 100 / 255)
}

# === Data Collection Thread (Robust OBD-II Polling) ===
def collect_data():
    global bus
    while True:
        timestamp = time.time()
        row = {'timestamp': timestamp, 'rpm': np.nan, 'speed': np.nan, 'coolant': np.nan, 'throttle': np.nan}

        if bus is not None:
            # Send all PID requests in rapid succession
            for pid_code, _ in PIDS.values():
                msg = can.Message(
                    arbitration_id=0x7DF,
                    data=[0x02, 0x01, pid_code, 0, 0, 0, 0, 0],
                    is_extended_id=False,
                    is_fd=False  # OBD-II requests are always Classic CAN frames
                )
                try:
                    bus.send(msg, timeout=0.1)
                except:
                    pass
            time.sleep(0.06)

            # Collect responses (up to 100ms window)
            responses = {}
            deadline = time.time() + 0.1
            while time.time() < deadline:
                try:
                    msg = bus.recv(timeout=0.02)
                    if msg is None:
                        continue
                    if (0x7E8 <= msg.arbitration_id <= 0x7EF and
                        len(msg.data) >= 4 and
                        msg.data[0] == 0x03 and msg.data[1] == 0x41):
                        pid = msg.data[2]
                        data_bytes = msg.data[3:]
                        responses[pid] = data_bytes[:2]  # Most PIDs use A and B
                except:
                    continue

            # Parse known PIDs
            for name, (pid_code, scaler) in PIDS.items():
                if pid_code in responses:
                    db = responses[pid_code]
                    a = db[0]
                    b = db[1] if len(db) > 1 else 0
                    row[name] = scaler(a, b)

        else:
            # Mock mode with occasional anomalies
            import random
            anomaly = random.random() < 0.04
            row.update({
                'rpm': random.uniform(6000, 8500) if anomaly else random.uniform(750, 3200),
                'speed': random.uniform(0, 180),
                'coolant': random.uniform(115, 145) if anomaly else random.uniform(82, 105),
                'throttle': random.uniform(92, 100) if anomaly else random.uniform(0, 100)
            })

        # Save to DB and get ID
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.execute(
                "INSERT INTO obd_data (timestamp, rpm, speed, coolant, throttle) VALUES (?, ?, ?, ?, ?)",
                (row['timestamp'], row['rpm'], row['speed'], row['coolant'], row['throttle'])
            )
            row_id = cur.lastrowid
            conn.execute("DELETE FROM obd_data WHERE id NOT IN (SELECT id FROM obd_data ORDER BY id DESC LIMIT 600)")
            conn.commit()
            conn.close()

        if not data_queue.full():
            data_queue.put((row_id, row))

        time.sleep(SAMPLE_RATE)

# === Anomaly Detection Thread ===
def model_anomalies():
    global model
    time.sleep(20)
    while True:
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            df = pd.read_sql_query("SELECT rpm, speed, coolant, throttle FROM obd_data ORDER BY id DESC LIMIT ?", conn, params=(TRAIN_SAMPLES,))
            conn.close()

        if len(df) >= 50:
            features = df.ffill().bfill().values
            if model is None:
                model = GaussianMixture(n_components=MODEL_COMPONENTS, covariance_type='full', random_state=42)
            model.fit(features)

            latest = features[-15:]
            scores = model.score_samples(latest)
            threshold = np.mean(scores) - ANOMALY_THRESHOLD * np.std(scores)

            with db_lock:
                conn = sqlite3.connect(DB_PATH)
                for score in scores:
                    anomaly = 1 if score < threshold else 0
                    conn.execute("UPDATE obd_data SET anomaly = ? WHERE id = (SELECT id FROM obd_data WHERE anomaly = 0 ORDER BY id DESC LIMIT 1)", (anomaly,))
                conn.commit()
                conn.close()

        time.sleep(6.0)

# === Web Dashboard ===
@app.route('/')
def dashboard():
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>F-250 OBD-II Live Monitor</title>
        <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.js"></script>
        <style>
            body { font-family: system-ui, sans-serif; background: #0d1b2a; color: #e0e1dd; margin: 20px; }
            h1 { color: #778da9; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }
            .card { background: #1b263b; padding: 15px; border-radius: 10px; text-align: center; border: 1px solid #415a77; }
            .value { font-size: 2em; font-weight: bold; }
            .label { color: #778da9; }
            .anomaly { background: #580000 !important; border-color: #900; animation: pulse 1s infinite; }
            @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.7; } }
            .chart { height: 400px; background: #1b263b; border-radius: 10px; padding: 10px; margin: 20px 0; }
        </style>
    </head>
    <body>
        <h1>Ford F-250 7.3L Powerstroke – OBD-II Monitor</h1>
        <div class="grid" id="metrics"></div>
        <div class="chart"><div id="rpm"></div></div>
        <div class="chart"><div id="anomaly"></div></div>

        <script>
            const socket = io();
            const rpmTrace = { x: [], y: [], type: 'scatter', name: 'RPM', line: {color: '#40c9ff'} };
            const anomalyTrace = { x: [], y: [], type: 'scatter', name: 'Anomaly', line: {color: '#ff006e'} };

            socket.on('update', data => {
                document.getElementById('metrics').innerHTML = '';
                ['rpm', 'speed', 'coolant', 'throttle'].forEach(k => {
                    const div = document.createElement('div');
                    div.className = 'card' + (data.anomaly ? ' anomaly' : '');
                    div.innerHTML = `<div class="label">${k.toUpperCase()}</div><div class="value">${isNaN(data[k]) ? '—' : data[k].toFixed(1)}</div>`;
                    document.getElementById('metrics').appendChild(div);
                });

                const t = new Date(data.timestamp * 1000);
                rpmTrace.x.push(t); rpmTrace.y.push(data.rpm || 0);
                anomalyTrace.x.push(t); anomalyTrace.y.push(data.anomaly ? 1 : 0);
                [rpmTrace, anomalyTrace].forEach(trace => {
                    if (trace.x.length > 60) { trace.x.shift(); trace.y.shift(); }
                });

                Plotly.react('rpm', [rpmTrace], {title: 'Engine RPM', paper_bgcolor: '#0d1b2a', plot_bgcolor: '#1b263b', font: {color: '#e0e1dd'}});
                Plotly.react('anomaly', [anomalyTrace], {title: 'Anomaly Flag (1 = Detected)', paper_bgcolor: '#0d1b2a', plot_bgcolor: '#1b263b', font: {color: '#e0e1dd'}});
            });
        </script>
    </body>
    </html>
    ''')

# === SocketIO Broadcaster ===
def emit_updates():
    while True:
        if not data_queue.empty():
            row_id, row = data_queue.get()
            with db_lock:
                conn = sqlite3.connect(DB_PATH)
                cur = conn.execute("SELECT anomaly FROM obd_data WHERE id = ?", (row_id,))
                result = cur.fetchone()
                conn.close()
            row['anomaly'] = bool(result[0]) if result else False
            socketio.emit('update', row)
        time.sleep(0.08)

# === Main ===
if __name__ == '__main__':
    threading.Thread(target=collect_data, daemon=True).start()
    threading.Thread(target=model_anomalies, daemon=True).start()
    threading.Thread(target=emit_updates, daemon=True).start()

    print("PiCAN FD Zero OBD-II Monitor Starting...")
    print("Dashboard: http://192.168.1.106:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)