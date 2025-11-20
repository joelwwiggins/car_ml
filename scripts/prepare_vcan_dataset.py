"""Convert candump/VCAN logs into sequence data for training the CNN autoencoder."""
import argparse
from pathlib import Path
from typing import Dict, List

import numpy as np

PID_FEATURES = [
    (0x04, 'calc_load'),
    (0x05, 'engine_temp'),
    (0x06, 'short_fuel_trim'),
    (0x07, 'long_fuel_trim'),
    (0x0B, 'intake_pressure'),
    (0x0C, 'engine_rpm'),
    (0x0D, 'vehicle_speed'),
    (0x0E, 'timing_advance'),
    (0x0F, 'intake_temp'),
    (0x10, 'mass_air_flow'),
    (0x11, 'throttle_pos'),
    (0x2F, 'fuel_level'),
]

PID_TO_NAME = {pid: name for pid, name in PID_FEATURES}
FEATURE_ORDER = [name for _, name in PID_FEATURES]


def parse_candump_line(line: str) -> Dict[str, float] | None:
    parts = line.strip().split()
    if len(parts) < 4:
        return None

    frame = parts[3]
    if '#' not in frame:
        return None

    arb_hex, payload_hex = frame.split('#', 1)
    try:
        arb_id = int(arb_hex, 16)
        payload = bytes.fromhex(payload_hex)
    except ValueError:
        return None

    # We only care about ECU responses
    if arb_id != 0x7E8 or len(payload) < 3:
        return None

    pid = payload[2]
    if pid not in PID_TO_NAME:
        return None

    value = decode_pid(pid, payload)
    if value is None:
        return None

    return {PID_TO_NAME[pid]: value}


def decode_pid(pid: int, payload: bytes) -> float | None:
    value = None
    if pid in {0x04, 0x05, 0x06, 0x07, 0x0B, 0x0D, 0x0E, 0x0F, 0x11, 0x2F}:
        value = payload[3] if len(payload) > 3 else None
    elif pid in {0x0C, 0x10} and len(payload) >= 5:
        value = payload[3] * 256 + payload[4]

    if value is None:
        return None

    if pid == 0x04:
        return (value * 100) / 255
    if pid == 0x05:
        return value - 40
    if pid in {0x06, 0x07}:
        return (value - 128) * 100 / 128
    if pid == 0x0B:
        return value
    if pid == 0x0C:
        return value / 4
    if pid == 0x0D:
        return value
    if pid == 0x0E:
        return (value / 2) - 64
    if pid == 0x0F:
        return value - 40
    if pid == 0x10:
        return value / 100
    if pid == 0x11:
        return (value * 100) / 255
    if pid == 0x2F:
        return (value * 100) / 255
    return None


def load_records(log_path: Path) -> List[List[float]]:
    history = [{name: 0.0 for name in FEATURE_ORDER}]
    records = []

    with log_path.open() as fh:
        for line in fh:
            measurement = parse_candump_line(line)
            if not measurement:
                continue

            history[0].update(measurement)
            records.append([history[0][name] for name in FEATURE_ORDER])

    return records


def build_sequences(records: List[List[float]], sequence_length: int) -> np.ndarray:
    if len(records) < sequence_length:
        return np.empty((0, sequence_length, len(FEATURE_ORDER)), dtype=np.float32)

    sequences = []
    for idx in range(sequence_length, len(records) + 1):
        window = records[idx - sequence_length:idx]
        sequences.append(window)
    return np.array(sequences, dtype=np.float32)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert candump logs into CNN training sequences.")
    parser.add_argument("--log-file", required=True, type=Path, help="Path to candump/vcan dump file")
    parser.add_argument("--sequence-length", type=int, default=32)
    parser.add_argument("--output", type=Path, default=Path("data/vcan_sequences.npz"))
    parser.add_argument("--min-sequences", type=int, default=128)
    args = parser.parse_args()

    if not args.log_file.exists():
        raise SystemExit(f"Log file not found: {args.log_file}")

    print(f"Parsing {args.log_file}... this may take a moment if the log is large")
    records = load_records(args.log_file)
    sequences = build_sequences(records, args.sequence_length)

    if sequences.shape[0] < args.min_sequences:
        raise SystemExit(
            f"Only {sequences.shape[0]} sequences extracted, need at least {args.min_sequences}. Run a longer capture."
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output, sequences=sequences)
    print(f"Saved {sequences.shape[0]} sequences (shape {sequences.shape}) to {args.output}")


if __name__ == "__main__":
    main()
