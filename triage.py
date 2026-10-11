
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).parent
FEATURES_FILE = BASE_DIR / "data" / "features.csv"
BASELINE_FILE = BASE_DIR / "data" / "baseline.csv"
RESULTS_FILE = BASE_DIR / "data" / "triage_results.csv"

# Experimental demo thresholds, not real machine safety limits.
OBSERVE_RATIO = 1.5
INSPECT_RATIO = 2.0


def main():
    df = pd.read_csv(FEATURES_FILE)

    baseline_data = df[
        (df["split"] == "train") &
        (df["label"] == 0)
    ].copy()

    if baseline_data.empty:
        raise ValueError("No label=0 training records available for baseline.")

    baseline = (
        baseline_data
        .groupby(["asset_id", "sensor"])["rms"]
        .agg(
            baseline_rms="median",
            baseline_count="count",
        )
        .reset_index()
    )

    baseline.to_csv(BASELINE_FILE, index=False)

    results = df.merge(
        baseline,
        on=["asset_id", "sensor"],
        how="left",
        validate="many_to_one",
    )

    valid_baseline = results["baseline_rms"] > 0

    results["rms_ratio"] = (
        results["rms"] / results["baseline_rms"].where(valid_baseline)
    )

    # Default status
    results["status"] = "NORMAL"

    # Exclude records with label -1 from triage decisions.
    excluded = results["label"] == -1
    results.loc[excluded, "status"] = "EXCLUDED"

    results.loc[
        (results["rms_ratio"] >= OBSERVE_RATIO) & ~excluded,
        "status",
    ] = "OBSERVE"

    results.loc[
        (results["rms_ratio"] >= INSPECT_RATIO) & ~excluded,
        "status",
    ] = "INSPECT"

    results.loc[
        results["baseline_rms"].isna() & ~excluded,
        "status",
    ] = "NO_BASELINE"

    results["priority"] = results["status"].map({
        "INSPECT": 1,
        "OBSERVE": 2,
        "NORMAL": 3,
        "NO_BASELINE": 4,
        "EXCLUDED": 5,
    })

    results = results.sort_values(
        ["priority", "rms_ratio"],
        ascending=[True, False],
        na_position="last",
    )

    results.to_csv(RESULTS_FILE, index=False)

    print(f"Baseline saved: {BASELINE_FILE}")
    print(f"Triage results saved: {RESULTS_FILE}")
    print("\nStatus counts:")
    print(results["status"].value_counts().to_string())

    print("\nHighest-priority records:")
    print(
        results[
            [
                "asset_id", "split", "sensor", "signal_index",
                "label", "rms", "baseline_rms", "rms_ratio", "status",
            ]
        ].head(10).to_string(index=False)
    )


if __name__ == "__main__":
    main()
