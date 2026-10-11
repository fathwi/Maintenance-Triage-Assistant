
from pathlib import Path
from collections import Counter

import numpy as np
from scipy.io import loadmat

DATA_DIR = Path(__file__).parent / "data"


def summarize_value(name, value):
    value = np.asarray(value)

    print(f"  {name}: shape={value.shape}, dtype={value.dtype}")

    if name == "label":
        labels, counts = np.unique(value, return_counts=True)
        print("    Label counts:", dict(zip(labels.tolist(), counts.tolist())))

    elif name == "samplingRate":
        print("    Unique values:", np.unique(value)[:10])

    elif name == "rawData" and value.dtype != object:
        print("    First signal samples:", value[0, :10])
        print("    Overall min/max:", float(np.min(value)), float(np.max(value)))


def inspect_file(path):
    print(f"\n{'=' * 60}\nFile: {path.relative_to(DATA_DIR)}")

    mat = loadmat(path, squeeze_me=False, struct_as_record=False)

    for key, value in mat.items():
        if key.startswith("__"):
            continue

        print(f"\nTop-level variable: {key}")

        if not isinstance(value, np.ndarray) or value.dtype.names is None:
            print(f"  shape={getattr(value, 'shape', None)}")
            continue

        struct = value.flat[0]

        for field in getattr(struct, "_fieldnames", []):
            field_value = getattr(struct, field)

            if field in {"rawData", "samplingRate", "label", "time"}:
                summarize_value(field, field_value)
            elif isinstance(field_value, np.ndarray):
                print(f"  {field}: shape={field_value.shape}, dtype={field_value.dtype}")
            else:
                print(f"  {field}: {type(field_value).__name__}")


def main():
    files = sorted(DATA_DIR.rglob("*.mat"))

    if not files:
        raise FileNotFoundError(f"No .mat files found under {DATA_DIR}")

    print(f"Found {len(files)} MAT files.")

    for path in files:
        inspect_file(path)


if __name__ == "__main__":
    main()
