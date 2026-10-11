
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.io import loadmat
from scipy.stats import kurtosis

DATA_DIR = Path(__file__).parent / "data" / "sca"
OUTPUT_FILE = Path(__file__).parent / "data" / "features.csv"


def unwrap(value):
    while isinstance(value, np.ndarray) and value.dtype == object and value.size == 1:
        value = value.item()
    return value


def get_struct_record(value):
    value = unwrap(value)
    if not isinstance(value, np.ndarray) or value.dtype.names is None:
        return None
    return value.flat[0]


def get_scalar_per_signal(value, index, default=np.nan):
    values = np.asarray(unwrap(value)).ravel()
    if index >= len(values):
        return default
    try:
        return float(values[index])
    except (TypeError, ValueError):
        return default


def get_label_per_signal(value, index):
    values = np.asarray(unwrap(value)).ravel()
    if index >= len(values):
        return None
    try:
        return int(values[index])
    except (TypeError, ValueError):
        return None


def extract_signals(raw_data):
    raw_data = unwrap(raw_data)

    if not isinstance(raw_data, np.ndarray):
        return []

    if raw_data.dtype != object:
        if raw_data.ndim == 1:
            return [np.asarray(raw_data, dtype=float).ravel()]
        if raw_data.ndim == 2:
            return [np.asarray(row, dtype=float).ravel() for row in raw_data]
        return []

    signals = []
    for item in raw_data.ravel():
        item = unwrap(item)
        try:
            signal = np.asarray(item, dtype=float).ravel()
            if signal.size > 0:
                signals.append(signal)
        except (TypeError, ValueError):
            continue
    return signals


def main():
    rows = []

    files = sorted(DATA_DIR.rglob("*.mat"))
    if not files:
        raise FileNotFoundError(f"No MAT files found in {DATA_DIR}")

    for path in files:
        split = path.stem.lower()
        asset_id = path.parent.name

        mat = loadmat(path, squeeze_me=False, struct_as_record=True)

        for sensor in ("FS", "DS", "Upper", "Lower"):
            if sensor not in mat:
                continue

            record = get_struct_record(mat[sensor])
            if record is None:
                continue

            signals = extract_signals(record["rawData"])
            labels = np.asarray(unwrap(record["label"])).ravel()
            sampling_rates = np.asarray(
                unwrap(record["samplingRate"])
            ).ravel()
            rpms = np.asarray(unwrap(record["RPM"])).ravel()

            for i, signal in enumerate(signals):
                if signal.size < 2 or not np.all(np.isfinite(signal)):
                    continue

                rms = float(np.sqrt(np.mean(signal ** 2)))
                peak_to_peak = float(np.ptp(signal))
                peak = float(np.max(np.abs(signal)))
                crest_factor = peak / rms if rms > 0 else np.nan

                rows.append({
                    "asset_id": asset_id,
                    "split": split,
                    "sensor": sensor,
                    "signal_index": i,
                    "label": get_label_per_signal(labels, i),
                    "sampling_rate": get_scalar_per_signal(sampling_rates, i),
                    "rpm": get_scalar_per_signal(rpms, i),
                    "signal_length": int(signal.size),
                    "rms": rms,
                    "peak_to_peak": peak_to_peak,
                    "kurtosis": float(kurtosis(signal, fisher=False)),
                    "crest_factor": crest_factor,
                })

    if not rows:
        raise RuntimeError("No valid signals extracted. Check the MAT structure.")

    df = pd.DataFrame(rows)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_FILE, index=False)

    print(f"Extracted {len(df)} signals.")
    print(f"Saved to: {OUTPUT_FILE}")
    print("\nSignals by asset, split, and sensor:")
    print(df.groupby(["asset_id", "split", "sensor"]).size().to_string())
    print("\nLabel counts:")
    print(df["label"].value_counts(dropna=False).sort_index().to_string())
    print("\nFirst rows:")
    print(df.head().to_string(index=False))


if __name__ == "__main__":
    main()
