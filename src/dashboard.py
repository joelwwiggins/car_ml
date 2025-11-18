#!/usr/bin/env python3
"""
Simple Web Dashboard for OBD2 Monitoring
Displays Prometheus metrics in a web interface optimized for mobile/RPi
"""

from flask import Flask, render_template_string, jsonify, request
import requests
import time
import threading
import logging
from functools import wraps

app = Flask(__name__)

# Simple authentication
USERNAME = 'admin'
PASSWORD = 'password'  # Change in production

def check_auth(username, password):
    return username == USERNAME and password == PASSWORD

def authenticate():
    return jsonify({'error': 'Authentication required'}), 401

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

# Prometheus endpoint
METRICS_URL = "http://localhost:8000/metrics"

# Cache for metrics
metrics_cache = {}
cache_timestamp = 0
CACHE_DURATION = 5  # seconds

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OBD2 Vehicle Monitor</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .metric-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }
        .metric-card {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
            border-left: 4px solid #007bff;
        }
        .metric-value {
            font-size: 2em;
            font-weight: bold;
            color: #007bff;
        }
        .metric-label {
            font-size: 0.9em;
            color: #666;
            margin-top: 5px;
        }
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
        }
        .status-normal { background-color: #28a745; }
        .status-warning { background-color: #ffc107; }
        .status-error { background-color: #dc3545; }
        .anomaly-score {
            margin: 20px 0;
            padding: 15px;
            border-radius: 8px;
        }
        .chart-container {
            margin: 20px 0;
            height: 200px;
        }
        .refresh-btn {
            background: #007bff;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            margin: 10px 0;
        }
        .refresh-btn:hover {
            background: #0056b3;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚗 OBD2 Vehicle Monitor</h1>
        <p>Real-time vehicle diagnostics with anomaly detection</p>

        <button class="refresh-btn" onclick="location.reload()">🔄 Refresh Data</button>

        <div class="metric-grid">
            <div class="metric-card">
                <div class="metric-value" id="engine-temp">--</div>
                <div class="metric-label">Engine Temp (°C)</div>
            </div>
            <div class="metric-card">
                <div class="metric-value" id="engine-rpm">--</div>
                <div class="metric-label">Engine RPM</div>
            </div>
            <div class="metric-card">
                <div class="metric-value" id="vehicle-speed">--</div>
                <div class="metric-label">Speed (km/h)</div>
            </div>
            <div class="metric-card">
                <div class="metric-value" id="fuel-level">--</div>
                <div class="metric-label">Fuel Level (%)</div>
            </div>
            <div class="metric-card">
                <div class="metric-value" id="battery-voltage">--</div>
                <div class="metric-label">Battery (V)</div>
            </div>
        </div>

        <div class="anomaly-score">
            <h3>Anomaly Detection Status</h3>
            <div class="metric-card">
                <div class="status-indicator status-normal" id="status-indicator"></div>
                <span id="anomaly-text">System Normal</span>
                <div style="margin-top: 10px;">
                    <div class="metric-value" id="anomaly-score">--</div>
                    <div class="metric-label">Anomaly Score (0-1)</div>
                </div>
            </div>
        </div>

        <div class="metric-grid">
            <div class="metric-card">
                <div class="metric-value" id="data-points">--</div>
                <div class="metric-label">Data Points Collected</div>
            </div>
            <div class="metric-card">
                <div class="metric-value" id="error-count">--</div>
                <div class="metric-label">Communication Errors</div>
            </div>
            <div class="metric-card">
                <div class="metric-value" id="uptime">--</div>
                <div class="metric-label">System Uptime</div>
            </div>
        </div>
    </div>

    <script>
        async function updateMetrics() {
            try {
                const response = await fetch('/api/metrics');
                const data = await response.json();

                // Update metrics
                document.getElementById('engine-temp').textContent = data.engine_temp || '--';
                document.getElementById('engine-rpm').textContent = data.engine_rpm || '--';
                document.getElementById('vehicle-speed').textContent = data.vehicle_speed || '--';
                document.getElementById('fuel-level').textContent = (data.fuel_level || '--');
                document.getElementById('battery-voltage').textContent = data.battery_voltage || '--';
                document.getElementById('anomaly-score').textContent = data.anomaly_score || '--';
                document.getElementById('data-points').textContent = data.data_points || '--';
                document.getElementById('error-count').textContent = data.error_count || '--';
                document.getElementById('uptime').textContent = data.uptime || '--';

                // Update anomaly status
                const score = parseFloat(data.anomaly_score) || 0;
                const indicator = document.getElementById('status-indicator');
                const text = document.getElementById('anomaly-text');

                indicator.className = 'status-indicator';
                if (score > 0.8) {
                    indicator.classList.add('status-error');
                    text.textContent = 'CRITICAL ANOMALY';
                } else if (score > 0.6) {
                    indicator.classList.add('status-warning');
                    text.textContent = 'Warning - Check Vehicle';
                } else {
                    indicator.classList.add('status-normal');
                    text.textContent = 'System Normal';
                }

            } catch (error) {
                console.error('Failed to update metrics:', error);
            }
        }

        // Update metrics every 2 seconds
        setInterval(updateMetrics, 2000);
        updateMetrics(); // Initial load
    </script>
</body>
</html>
"""

def query_prometheus(query):
    """Query metrics from collector's /metrics endpoint."""
    try:
        response = requests.get(METRICS_URL, timeout=5)
        if response.status_code == 200:
            lines = response.text.split('\n')
            for line in lines:
                if line.startswith(query):
                    parts = line.split()
                    if len(parts) >= 2:
                        return parts[1]
    except Exception as e:
        logging.error(f"Metrics query failed: {e}")
    return None

def get_metrics():
    """Get all metrics from Prometheus."""
    global cache_timestamp, metrics_cache
    current_time = time.time()

    # Use cache if recent
    if current_time - cache_timestamp < CACHE_DURATION:
        return metrics_cache

    metrics = {}

    # Query individual metrics
    metrics_queries = {
        'engine_temp': 'obd2_engine_temperature',
        'engine_rpm': 'obd2_engine_rpm',
        'vehicle_speed': 'obd2_vehicle_speed',
        'fuel_level': 'obd2_fuel_level',
        'battery_voltage': 'obd2_battery_voltage',
        'anomaly_score': 'obd2_anomaly_score',
        'data_points': 'obd2_data_points_total',
        'error_count': 'obd2_errors_total',
    }

    for key, query in metrics_queries.items():
        value = query_prometheus(query)
        if value:
            try:
                metrics[key] = float(value)
            except ValueError:
                metrics[key] = value

    # Calculate uptime (simplified)
    metrics['uptime'] = f"{int(current_time - cache_timestamp)}s" if cache_timestamp > 0 else "0s"

    # Update cache
    metrics_cache.update(metrics)
    cache_timestamp = current_time

    return metrics

@app.route('/')
@requires_auth
def dashboard():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/metrics')
@requires_auth
def api_metrics():
    return jsonify(get_metrics())

@app.route('/health')
def health():
    return {'status': 'healthy', 'timestamp': time.time()}

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    app.run(host='0.0.0.0', port=5000, debug=False)