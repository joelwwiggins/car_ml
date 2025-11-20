#!/usr/bin/env python3
"""
Quantization script to convert Keras CNN autoencoder to INT8 TFLite model
Optimized for Raspberry Pi Zero 2W inference
"""

import os
os.environ["TF_USE_LEGACY_KERAS"] = "1"

import numpy as np
import tensorflow as tf
from tensorflow import lite as tflite
import os

from src.model import FEATURE_DIM, FEATURE_ORDER, FEATURE_RANGES, SEQUENCE_LENGTH, create_cnn_autoencoder


def representative_dataset_gen(sequence_length=SEQUENCE_LENGTH, feature_dim=FEATURE_DIM, num_samples=120):
    ranges = [FEATURE_RANGES[name] for name in FEATURE_ORDER]
    for _ in range(num_samples):
        sample = []
        for _ in range(sequence_length):
            features = []
            for j in range(feature_dim):
                low, high = ranges[j]
                features.append(np.random.uniform(low, high))
            sample.append(features)
        yield [np.array([sample], dtype=np.float32)]

def quantize_model(weight_path, output_model_path):
    """Convert Keras model weights to INT8 quantized TFLite model."""
    print(f"Reconstructing model from weights ({weight_path})")
    model = create_cnn_autoencoder(SEQUENCE_LENGTH, FEATURE_DIM)
    model.load_weights(weight_path)
    print("Model weights loaded")

    # Save as TF SavedModel to avoid Keras 3 compatibility issues
    saved_model_dir = "temp_saved_model"
    tf.saved_model.save(model, saved_model_dir)
    
    converter = tflite.TFLiteConverter.from_saved_model(saved_model_dir)

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
    weight_size = os.path.getsize(weight_path)
    quantized_size = os.path.getsize(output_model_path)
    print(f"Weight file: {weight_size / 1024:.1f} KB")
    print(f"Quantized model: {quantized_size / 1024:.1f} KB")

if __name__ == "__main__":
    # Paths
    weight_path = "../models/cnn_model.weights.h5"
    output_model = "../models/cnn_model_int8.tflite"

    if not os.path.exists(weight_path):
        print(f"Error: {weight_path} not found. Please ensure the model is trained first.")
        exit(1)

    quantize_model(weight_path, output_model)