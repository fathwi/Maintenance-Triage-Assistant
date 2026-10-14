
import csv
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

FEATURES_FILE = (
    DATA_DIR / "features.csv"
    if (DATA_DIR / "features.csv").exists()
    else ROOT / "features.csv"
)

BASELINE_FILE = (
    DATA_DIR / "baseline.csv"
    if (DATA_DIR / "baseline.csv").exists()
    else ROOT / "baseline.csv"
)

OUTPUT_FILE = DATA_DIR / "thresholds.csv"


def quantile(values, q):
    values = sorted(values)

    if not values:
        raise ValueError("Cannot calculate quantile from empty data")

    position = (len(values) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower

    return (
        values[lower] * (1 - fraction)
        + values[upper] * fraction
    )


def read_baselines():
    baselines = {}

    with BASELINE_FILE.open(
        "r", newline="", encoding="utf-8-sig"
    ) as file:
        for row in csv.DictReader(file):
            key = (
                row["asset_id"].strip(),
                row["sensor"].strip(),
            )

            baseline = float(row["baseline_rms"])

            if math.isfinite(baseline) and baseline > 0:
                baselines[key] = baseline

    return baselines


def main():
    if not FEATURES_FILE.exists():
        raise FileNotFoundError(
            f"Features file not found: {FEATURES_FILE}"
        )

    if not BASELINE_FILE.exists():
        raise FileNotFoundError(
            f"Baseline file not found: {BASELINE_FILE}"
        )

    baselines = read_baselines()
    normal_ratios = defaultdict(list)

    with FEATURES_FILE.open(
        "r", newline="", encoding="utf-8-sig"
    ) as file:
        reader = csv.DictReader(file)

        required = {
            "asset_id", "sensor", "split", "label", "rms"
        }

        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(
                "features.csv must contain: "
                + ", ".join(sorted(required))
            )

        for row in reader:
            if row["split"].strip().lower() != "train":
                continue

            if row["label"].strip() != "0":
                continue

            key = (
                row["asset_id"].strip(),
                row["sensor"].strip(),
            )

            baseline = baselines.get(key)

            if baseline is None:
                continue

            try:
                rms = float(row["rms"])
                ratio = rms / baseline
            except (ValueError, TypeError, ZeroDivisionError):
                continue

            if math.isfinite(ratio) and ratio >= 0:
                normal_ratios[key].append(ratio)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    rows_written = 0

    with OUTPUT_FILE.open(
        "w", newline="", encoding="utf-8"
    ) as file:
        fieldnames = [
            "asset_id",
            "sensor",
            "observe_ratio",
            "inspect_ratio",
            "normal_count",
            "baseline_rms",
        ]

        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        print("\nCALIBRATED THRESHOLDS")
        print("-" * 65)

        for key in sorted(normal_ratios):
            ratios = normal_ratios[key]

            # Avoid relying on very small samples.
            if len(ratios) < 20:
                print(
                    f"SKIPPED {key}: only {len(ratios)} "
                    "normal training rows"
                )
                continue

            observe = quantile(ratios, 0.95)
            inspect = quantile(ratios, 0.99)

            # Keep INSPECT strictly above OBSERVE.
            inspect = max(inspect, observe)

            asset_id, sensor = key

            writer.writerow({
                "asset_id": asset_id,
                "sensor": sensor,
                "observe_ratio": round(observe, 6),
                "inspect_ratio": round(inspect, 6),
                "normal_count": len(ratios),
                "baseline_rms": round(baselines[key], 8),
            })

            rows_written += 1

            print(
                f"Asset={asset_id}, Sensor={sensor} | "
                f"N={len(ratios)} | "
                f"OBSERVE={observe:.4f} | "
                f"INSPECT={inspect:.4f}"
            )

    print("-" * 65)
    print(f"Threshold groups written: {rows_written}")
    print(f"Output: {OUTPUT_FILE}")

    if rows_written == 0:
        raise RuntimeError(
            "No threshold groups generated. "
            "Check file paths, CSV columns, split values and labels."
        )


if __name__ == "__main__":
    main()
