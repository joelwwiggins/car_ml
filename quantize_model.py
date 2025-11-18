#!/usr/bin/env python3
"""
Quantization script to convert Keras CNN autoencoder to INT8 TFLite model
Optimized for Raspberry Pi Zero 2W inference
"""

import numpy as np
import tensorflow as tf
from tensorflow import lite as tflite
import os

def create_cnn_autoencoder(input_shape=(32, 7)):
    """Recreate the CNN autoencoder architecture (must match training model)."""
    encoder_input = tf.keras.layers.Input(shape=input_shape)
    x = tf.keras.layers.Conv1D(32, 7, activation='relu', padding='same')(encoder_input)
    x = tf.keras.layers.MaxPooling1D(2)(x)
    x = tf.keras.layers.Conv1D(16, 5, activation='relu', padding='same')(x)
    x = tf.keras.layers.MaxPooling1D(2)(x)
    x = tf.keras.layers.Conv1D(8, 3, activation='relu', padding='same')(x)
    encoded = tf.keras.layers.MaxPooling1D(2)(x)

    x = tf.keras.layers.Conv1D(8, 3, activation='relu', padding='same')(encoded)
    x = tf.keras.layers.UpSampling1D(2)(x)
    x = tf.keras.layers.Conv1D(16, 5, activation='relu', padding='same')(x)
    x = tf.keras.layers.UpSampling1D(2)(x)
    x = tf.keras.layers.Conv1D(32, 7, activation='relu', padding='same')(x)
    x = tf.keras.layers.UpSampling1D(2)(x)
    decoded = tf.keras.layers.Conv1D(7, 3, activation='linear', padding='same')(x)

    autoencoder = tf.keras.Model(encoder_input, decoded)
    return autoencoder

def representative_dataset_gen(sequence_length=32, feature_dim=7, num_samples=100):
    """Generate representative dataset for INT8 quantization."""
    # Use realistic OBD2 data ranges for better quantization
    ranges = {
        0: (70, 110),   # engine_temp
        1: (800, 4000), # engine_rpm
        2: (0, 120),    # vehicle_speed
        3: (10, 100),   # fuel_level
        4: (5, 50),     # mass_air_flow (scaled)
        5: (20, 40),    # intake_air_temp
        6: (0, 100),    # throttle_position
    }

    for _ in range(num_samples):
        sample = []
        for i in range(sequence_length):
            features = []
            for j in range(feature_dim):
                min_val, max_val = ranges[j]
                features.append(np.random.uniform(min_val, max_val))
            sample.append(features)
        yield [np.array([sample], dtype=np.float32)]

def quantize_model(input_model_path, output_model_path):
    """Convert Keras model to INT8 quantized TFLite model."""
    print(f"Loading model from {input_model_path}")

    # Load the trained Keras model
    model = tf.keras.models.load_model(input_model_path)
    print("Model loaded successfully")

    # Create converter
    converter = tflite.TFLiteConverter.from_keras_model(model)

    # Enable optimizations
    converter.optimizations = [tf.lite.Optimize.DEFAULT]

    # Enable INT8 quantization
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8

    # Provide representative dataset for quantization
    converter.representative_dataset = representative_dataset_gen

    print("Converting to INT8 TFLite...")
    tflite_model = converter.convert()

    # Save the quantized model
    with open(output_model_path, 'wb') as f:
        f.write(tflite_model)

    print(f"INT8 quantized model saved to {output_model_path}")

    # Print model size comparison
    original_size = os.path.getsize(input_model_path)
    quantized_size = os.path.getsize(output_model_path)
    print(".1f")
    print(".1f")

if __name__ == "__main__":
    # Paths
    input_model = "cnn_model.h5"
    output_model = "cnn_model_int8.tflite"

    if not os.path.exists(input_model):
        print(f"Error: {input_model} not found. Please ensure the model is trained first.")
        exit(1)

    quantize_model(input_model, output_model)