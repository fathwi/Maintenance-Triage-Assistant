
from pathlib import Path
import sqlite3
import pandas as pd

BASE_DIR = Path(__file__).parent
RESULTS_FILE = BASE_DIR / "data" / "triage_results.csv"
DB_FILE = BASE_DIR / "data" / "inspection_queue.db"


def connect():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def initialize():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS inspection_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id TEXT NOT NULL,
                sensor TEXT NOT NULL,
                split TEXT NOT NULL,
                signal_index INTEGER NOT NULL,
                rms REAL NOT NULL,
                baseline_rms REAL NOT NULL,
                rms_ratio REAL NOT NULL,
                priority INTEGER NOT NULL,
                status TEXT NOT NULL,
                acknowledged INTEGER NOT NULL DEFAULT 0,
                acknowledged_by TEXT,
                acknowledged_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(asset_id, sensor, split, signal_index)
            )
        """)


def sync_queue():
    if not RESULTS_FILE.exists():
        raise FileNotFoundError(f"Results file not found: {RESULTS_FILE}")

    df = pd.read_csv(RESULTS_FILE)

    # Only OBSERVE and INSPECT records belong in the queue.
    alerts = df[df["status"].isin(["OBSERVE", "INSPECT"])].copy()

    active_keys = set()

    with connect() as conn:
        # Insert new alerts or update existing ones.
        # Existing IDs and acknowledgement fields are preserved.
        for _, row in alerts.iterrows():
            if pd.isna(row["baseline_rms"]) or pd.isna(row["rms_ratio"]):
                continue

            key = (
                str(row["asset_id"]),
                str(row["sensor"]),
                str(row["split"]),
                int(row["signal_index"]),
            )
            active_keys.add(key)

            conn.execute("""
                INSERT INTO inspection_queue (
                    asset_id,
                    sensor,
                    split,
                    signal_index,
                    rms,
                    baseline_rms,
                    rms_ratio,
                    priority,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id, sensor, split, signal_index)
                DO UPDATE SET
                    rms = excluded.rms,
                    baseline_rms = excluded.baseline_rms,
                    rms_ratio = excluded.rms_ratio,
                    priority = excluded.priority,
                    status = excluded.status
            """, (
                *key,
                float(row["rms"]),
                float(row["baseline_rms"]),
                float(row["rms_ratio"]),
                int(row["priority"]),
                str(row["status"]),
            ))

        # Remove records that are no longer OBSERVE or INSPECT.
        existing = conn.execute("""
            SELECT id, asset_id, sensor, split, signal_index
            FROM inspection_queue
        """).fetchall()

        stale_ids = [
            row["id"]
            for row in existing
            if (
                row["asset_id"],
                row["sensor"],
                row["split"],
                row["signal_index"],
            ) not in active_keys
        ]

        if stale_ids:
            conn.executemany(
                "DELETE FROM inspection_queue WHERE id = ?",
                [(alert_id,) for alert_id in stale_ids],
            )

    print(f"Queue synchronized: {len(active_keys)} active alerts.")


def show_queue():
    with connect() as conn:
        rows = conn.execute("""
            SELECT *
            FROM inspection_queue
            ORDER BY priority ASC, rms_ratio DESC
        """).fetchall()

    if not rows:
        print("Inspection queue is empty.")
        return

    df = pd.DataFrame([dict(row) for row in rows])
    print(df.to_string(index=False))


def acknowledge(alert_id, technician):
    with connect() as conn:
        cursor = conn.execute("""
            UPDATE inspection_queue
            SET acknowledged = 1,
                acknowledged_by = ?,
                acknowledged_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (technician, alert_id))

        if cursor.rowcount == 0:
            print(f"No alert found with ID {alert_id}.")
        else:
            print(f"Alert {alert_id} acknowledged by {technician}.")


def main():
    initialize()
    sync_queue()

    print("\nCurrent inspection queue:")
    show_queue()

    print("\nTo acknowledge an alert, use:")
    print(
        "python -c \"from queue_manager import acknowledge; "
        "acknowledge(1, 'Technician 1')\""
    )


if __name__ == "__main__":
    main()
