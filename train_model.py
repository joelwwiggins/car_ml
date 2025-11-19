#!/usr/bin/env python3
"""
Training script for CNN autoencoder anomaly detection on OBD2 data
Computes RMSE during training and validation
"""

import numpy as np
import tensorflow as tf
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error
import matplotlib.pyplot as plt
import os

def create_cnn_autoencoder(input_shape=(32, 7)):
    """Create CNN autoencoder for OBD2 anomaly detection."""
    encoder_input = tf.keras.layers.Input(shape=input_shape)

    # Encoder
    x = tf.keras.layers.Conv1D(32, 7, activation='relu', padding='same')(encoder_input)
    x = tf.keras.layers.MaxPooling1D(2)(x)
    x = tf.keras.layers.Conv1D(16, 5, activation='relu', padding='same')(x)
    x = tf.keras.layers.MaxPooling1D(2)(x)
    x = tf.keras.layers.Conv1D(8, 3, activation='relu', padding='same')(x)
    encoded = tf.keras.layers.MaxPooling1D(2)(x)

    # Decoder
    x = tf.keras.layers.Conv1D(8, 3, activation='relu', padding='same')(encoded)
    x = tf.keras.layers.UpSampling1D(2)(x)
    x = tf.keras.layers.Conv1D(16, 5, activation='relu', padding='same')(x)
    x = tf.keras.layers.UpSampling1D(2)(x)
    x = tf.keras.layers.Conv1D(32, 7, activation='relu', padding='same')(x)
    x = tf.keras.layers.UpSampling1D(2)(x)
    decoded = tf.keras.layers.Conv1D(7, 3, activation='linear', padding='same')(x)

    autoencoder = tf.keras.Model(encoder_input, decoded)
    return autoencoder

def generate_synthetic_obd2_data(num_samples=10000, sequence_length=32):
    """Generate synthetic OBD2 data for training."""
    # Realistic ranges for 7 key PIDs (matching quantize_model.py)
    ranges = {
        0: (70, 110),   # engine_temp
        1: (800, 4000), # engine_rpm
        2: (0, 120),    # vehicle_speed
        3: (10, 100),   # fuel_level
        4: (5, 50),     # mass_air_flow (scaled)
        5: (20, 40),    # intake_air_temp
        6: (0, 100),    # throttle_position
    }

    data = []
    for _ in range(num_samples):
        sequence = []
        for _ in range(sequence_length):
            features = []
            for j in range(7):  # 7 features
                min_val, max_val = ranges[j]
                features.append(np.random.uniform(min_val, max_val))
            sequence.append(features)
        data.append(sequence)

    return np.array(data)

def train_model():
    """Train the CNN autoencoder and compute RMSE."""
    print("Generating synthetic OBD2 data...")
    data = generate_synthetic_obd2_data(num_samples=5000, sequence_length=32)

    # Split data
    train_data, val_data = train_test_split(data, test_size=0.2, random_state=42)

    # Normalize data
    scaler = StandardScaler()
    train_data_reshaped = train_data.reshape(-1, 7)
    scaler.fit(train_data_reshaped)
    train_data_normalized = scaler.transform(train_data_reshaped).reshape(train_data.shape)
    val_data_normalized = scaler.transform(val_data.reshape(-1, 7)).reshape(val_data.shape)

    print(f"Training data shape: {train_data_normalized.shape}")
    print(f"Validation data shape: {val_data_normalized.shape}")

    # Create model
    model = create_cnn_autoencoder(input_shape=(32, 7))
    model.compile(optimizer='adam', loss='mse')

    # Train model
    print("Training model...")
    history = model.fit(
        train_data_normalized, train_data_normalized,
        epochs=50,
        batch_size=32,
        validation_data=(val_data_normalized, val_data_normalized),
        verbose=1
    )

    # Evaluate on validation set
    print("Evaluating model...")
    val_predictions = model.predict(val_data_normalized)

    # Compute MSE and RMSE
    mse = mean_squared_error(val_data_normalized.flatten(), val_predictions.flatten())
    rmse = np.sqrt(mse)

    print(".6f")
    print(".6f")

    # Save the trained model
    model.save('cnn_model.h5')
    print("Model saved as cnn_model.h5")

    # Plot training history
    plt.figure(figsize=(10, 6))
    plt.plot(history.history['loss'], label='Training Loss')
    plt.plot(history.history['val_loss'], label='Validation Loss')
    plt.title('Model Loss During Training')
    plt.xlabel('Epoch')
    plt.ylabel('Loss (MSE)')
    plt.legend()
    plt.savefig('training_history.png')
    plt.show()

    return rmse

if __name__ == "__main__":
    rmse = train_model()
    print(f"\nFinal RMSE: {rmse:.6f}")