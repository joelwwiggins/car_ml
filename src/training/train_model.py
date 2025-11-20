#!/usr/bin/env python3
"""Train the CNN autoencoder with VCAN-aligned sequences and report RMSE."""

from __future__ import annotations

import os
os.environ["TF_USE_LEGACY_KERAS"] = "1"

import argparse
import os
from pathlib import Path
from typing import Tuple

import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from src.model import (
    FEATURE_DIM,
    FEATURE_ORDER,
    FEATURE_RANGES,
    SEQUENCE_LENGTH,
    create_cnn_autoencoder,
)

def generate_synthetic_sequences(num_samples: int, sequence_length: int) -> np.ndarray:
    data = np.zeros((num_samples, sequence_length, FEATURE_DIM), dtype=np.float32)
    for idx, feature in enumerate(FEATURE_ORDER):
        low, high = FEATURE_RANGES[feature]
        data[:, :, idx] = np.random.uniform(low, high, size=(num_samples, sequence_length))
    return data


def load_vcan_sequences(path: Path, sequence_length: int) -> np.ndarray:
    blob = np.load(path)
    sequences = blob['sequences']
    if sequences.ndim != 3:
        raise ValueError('Expected sequences to be 3-D (N, sequence_length, features).')
    if sequences.shape[1] != sequence_length:
        raise ValueError(
            f'Sequence length mismatch: dataset {sequences.shape[1]} vs expected {sequence_length}.')
    if sequences.shape[2] != FEATURE_DIM:
        raise ValueError('Feature dimension mismatch between dataset and collector expectations.')
    return sequences.astype(np.float32)


def prepare_dataset(sequences: np.ndarray, test_size: float) -> Tuple[np.ndarray, np.ndarray, StandardScaler]:
    train, val = train_test_split(sequences, test_size=test_size, shuffle=True, random_state=42)
    scaler = StandardScaler()
    scaler.fit(train.reshape(-1, FEATURE_DIM))
    train_scaled = scaler.transform(train.reshape(-1, FEATURE_DIM)).reshape(train.shape)
    val_scaled = scaler.transform(val.reshape(-1, FEATURE_DIM)).reshape(val.shape)
    return train_scaled, val_scaled, scaler


def plot_history(history: tf.keras.callbacks.History) -> None:
    plt.figure(figsize=(10, 6))
    plt.plot(history.history['loss'], label='training mse')
    plt.plot(history.history['val_loss'], label='validation mse')
    plt.title('CNN Autoencoder Loss')
    plt.xlabel('epoch')
    plt.ylabel('mse')
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig('training_history.png')
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description='Train CNN autoencoder on VCAN-aligned sequences.')
    parser.add_argument('--vcan-data', type=Path, help='NPZ file created from candump/vcan logs (data/vcan_sequences.npz).')
    parser.add_argument('--sequence-length', type=int, default=SEQUENCE_LENGTH)
    parser.add_argument('--epochs', type=int, default=40)
    parser.add_argument('--batch-size', type=int, default=32)
    parser.add_argument('--output', type=Path, default=Path('../models/cnn_model.keras'))
    parser.add_argument('--test-size', type=float, default=0.2)
    args = parser.parse_args()

    sequence_length = args.sequence_length
    if args.vcan_data and args.vcan_data.exists():
        print(f'Loading VCAN sequences from {args.vcan_data}')
        sequences = load_vcan_sequences(args.vcan_data, sequence_length)
    else:
        print('Warning: VCAN dataset missing; using synthetic sequences for now (deployments expect real data).')
        sequences = generate_synthetic_sequences(num_samples=6000, sequence_length=sequence_length)

    print(f'Training on {sequences.shape[0]} samples of shape ({sequence_length}, {FEATURE_DIM}).')
    train_data, val_data, _ = prepare_dataset(sequences, test_size=args.test_size)

    model = create_cnn_autoencoder(sequence_length, FEATURE_DIM)
    model.compile(optimizer=tf.keras.optimizers.Adam(1e-3), loss='mse')
    history = model.fit(
        train_data,
        train_data,
        epochs=args.epochs,
        batch_size=args.batch_size,
        validation_data=(val_data, val_data),
        verbose=1,
    )

    val_pred = model.predict(val_data)
    mse = mean_squared_error(val_data.flatten(), val_pred.flatten())
    rmse = np.sqrt(mse)
    print(f'Final RMSE (validation): {rmse:.6f}')

    model.save(args.output)
    print(f'Saved trained model to {args.output} ({args.output.stat().st_size / 1024:.1f} KB).')
    weights_path = args.output.with_suffix('.weights.h5')
    model.save_weights(weights_path)
    print(f'Saved weights to {weights_path}')

    plot_history(history)


if __name__ == '__main__':
    main()