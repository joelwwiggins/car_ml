# Simplified Dockerfile for production
FROM python:3.12-slim-bookworm

# Install minimal runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    can-utils \
    iproute2 \
    net-tools \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.prod.txt .
RUN pip install --no-cache-dir -r requirements.prod.txt

# Copy application files
COPY src/ .
COPY config/obd2_config.json config/
COPY models/cnn_model_int8.tflite models/

# Create non-root user
RUN groupadd -r app && useradd -r -g app app && \
    chown -R app:app /app
USER app

# Expose Prometheus port
EXPOSE 8000

# Run collector
CMD ["python3", "obd2_collector.py"]