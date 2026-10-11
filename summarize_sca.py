
from pathlib import Path

import numpy as np
from scipy.io import loadmat

DATA_DIR = Path(__file__).parent / "data" / "sca"


def unwrap(value):
    while isinstance(value, np.ndarray) and value.dtype == object and value.size == 1:
        value = value.item()
    return value


def signal_summary(raw_data):
    raw_data = unwrap(raw_data)

    print(
        f"    rawData: shape={getattr(raw_data, 'shape', None)}, "
        f"dtype={getattr(raw_data, 'dtype', None)}"
    )

    if not isinstance(raw_data, np.ndarray):
        print("      Unsupported rawData format")
        return

    if raw_data.dtype != object:
        if np.issubdtype(raw_data.dtype, np.number):
            print(f"      Min/Max: {np.min(raw_data):.4f}, {np.max(raw_data):.4f}")
            print(f"      Signal count: {raw_data.shape[0] if raw_data.ndim > 1 else 1}")
        return

    # Some MATLAB files store each signal inside an object array.
    signals = raw_data.ravel()
    print(f"      Object entries: {len(signals)}")

    for index, signal in enumerate(signals[:2]):
        signal = unwrap(signal)
        try:
            numeric = np.asarray(signal, dtype=float)
            print(
                f"      Example {index + 1}: shape={numeric.shape}, "
                f"min={np.min(numeric):.4f}, max={np.max(numeric):.4f}"
            )
        except (TypeError, ValueError):
            print(f"      Example {index + 1}: cannot convert to numeric array")


def inspect_struct(name, value):
    value = unwrap(value)

    if not isinstance(value, np.ndarray) or value.dtype.names is None:
        return

    record = value.flat[0]
    fields = value.dtype.names

    print(f"  {name} fields: {fields}")

    for field in fields:
        item = unwrap(record[field])

        if field == "rawData":
            signal_summary(item)

        elif field == "label":
            labels = np.asarray(item).ravel()
            unique, counts = np.unique(labels, return_counts=True)
            print(f"    label counts: {dict(zip(unique.tolist(), counts.tolist()))}")

        elif field in {"samplingRate", "RPM"}:
            values = np.asarray(item).ravel()
            if values.size:
                print(
                    f"    {field}: count={values.size}, "
                    f"range={values.min()} to {values.max()}"
                )


def main():
    files = sorted(DATA_DIR.rglob("*.mat"))

    if not files:
        raise FileNotFoundError(f"No MAT files in {DATA_DIR}")

    print(f"Found {len(files)} MAT files.")

    for path in files:
        print(f"\n{'=' * 60}\n{path.relative_to(DATA_DIR)}")

        mat = loadmat(path, squeeze_me=False, struct_as_record=True)

        for name in ("FS", "DS", "Upper", "Lower"):
            if name in mat:
                inspect_struct(name, mat[name])


if __name__ == "__main__":
    main()
