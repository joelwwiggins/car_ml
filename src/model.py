from __future__ import annotations

import os
os.environ["TF_USE_LEGACY_KERAS"] = "1"

from typing import Dict, Tuple

import tensorflow as tf

FEATURE_ORDER = [
    'calc_load',
    'engine_temp',
    'short_fuel_trim',
    'long_fuel_trim',
    'intake_pressure',
    'engine_rpm',
    'vehicle_speed',
    'timing_advance',
    'intake_temp',
    'mass_air_flow',
    'throttle_pos',
    'fuel_level',
]
FEATURE_DIM = len(FEATURE_ORDER)
SEQUENCE_LENGTH = 32
FEATURE_RANGES: Dict[str, Tuple[float, float]] = {
    'calc_load': (0, 100),
    'engine_temp': (20, 110),
    'short_fuel_trim': (-100, 100),
    'long_fuel_trim': (-100, 100),
    'intake_pressure': (20, 120),
    'engine_rpm': (0, 6000),
    'vehicle_speed': (0, 200),
    'timing_advance': (-64, 64),
    'intake_temp': (-40, 120),
    'mass_air_flow': (0, 200),
    'throttle_pos': (0, 100),
    'fuel_level': (0, 100),
}


def create_cnn_autoencoder(sequence_length: int = SEQUENCE_LENGTH, feature_dim: int = FEATURE_DIM) -> tf.keras.Model:
    encoder_input = tf.keras.layers.Input(shape=(sequence_length, feature_dim))
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
    decoded = tf.keras.layers.Conv1D(feature_dim, 3, activation='linear', padding='same')(x)
    return tf.keras.Model(encoder_input, decoded)
