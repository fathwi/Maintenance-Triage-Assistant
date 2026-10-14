# Project 05 - Maintenance Triage Assistant
# ESP32 / Wokwi / MicroPython
# Mode: Precalibrated Dataset Replay
#
# Files required beside main.py:
#   features.csv
#   baseline.csv
#   thresholds.csv
#
# Thresholds are calculated offline from TRAIN normal data.
# Test labels are used for evaluation only, never for decisions.

import time
import json
import network
import math
import os
import random
from machine import Pin

try:
    from umqtt.simple import MQTTClient
except ImportError:
    MQTTClient = None


# ================= CONFIG =================

WIFI_SSID = "Wokwi-GUEST"
WIFI_PASSWORD = ""

MQTT_HOST = "broker.hivemq.com"
MQTT_PORT = 1883

FEATURES_FILE = "features.csv"
BASELINE_FILE = "baseline.csv"
THRESHOLDS_FILE = "thresholds.csv"

TOPIC_ROOT = "muhammeedd1/triage"
REPLAY_INTERVAL_MS = 1000

# True only when you need false-alarm / detection numbers for the report.
# It is slow on Wokwi, and the dashboard stays offline until it finishes.
EVALUATE_ON_BOOT = False

# True  = each message is a randomly picked TEST row (instant start,
#         no scanning of the file) -> variety on the dashboard.
# False = test rows are replayed in file order.
RANDOM_REPLAY = True

PIN_LED_GREEN = 27
PIN_LED_RED = 13
PIN_BUZZER = 23

# ==========================================

green_led = Pin(PIN_LED_GREEN, Pin.OUT)
red_led = Pin(PIN_LED_RED, Pin.OUT)
buzzer = Pin(PIN_BUZZER, Pin.OUT)

wlan = network.WLAN(network.STA_IF)

mqtt_client = None
last_mqtt_attempt = 0
last_wifi_attempt = 0

baselines = {}
thresholds = {}
sequence_number = 0

feature_headers = []
split_column = -1
data_start = 0
file_size = 0
recent_offsets = []


# ---------- Utilities ----------

def parse_csv_line(line):
    return [
        value.strip().strip('"')
        for value in line.strip().split(",")
    ]


def number_or_none(value):
    try:
        value = str(value).strip()

        if not value or value.lower() in (
            "nan", "none", "null"
        ):
            return None

        number = float(value)

        if not math.isfinite(number):
            return None

        return number

    except (ValueError, TypeError):
        return None


def label_or_none(value):
    number = number_or_none(value)

    if number is None:
        return None

    return int(number)


def group_key(asset_id, sensor):
    return (
        str(asset_id).strip(),
        str(sensor).strip()
    )


def iter_feature_rows(split=None):
    # If split is given, rows from other splits are skipped BEFORE
    # building the dict, which makes skipping train rows much faster.
    with open(FEATURES_FILE, "r") as file:
        header_line = file.readline()

        if not header_line:
            raise ValueError("features.csv is empty")

        headers = parse_csv_line(header_line)
        names = [name.strip().lower() for name in headers]

        split_index = -1

        if split is not None:
            if "split" not in names:
                raise ValueError("features.csv has no split column")
            split_index = names.index("split")

        for line in file:
            if not line.strip():
                continue

            values = parse_csv_line(line)

            if len(values) < len(names):
                continue

            if (
                split_index >= 0
                and values[split_index].lower() != split
            ):
                continue

            row = {}

            for index, name in enumerate(names):
                row[name] = values[index]

            yield row


# ---------- Random replay support ----------

def init_random_replay():
    # Reads only the header line. No scan of the whole file.
    global feature_headers, split_column, data_start, file_size

    with open(FEATURES_FILE, "r") as file:
        header_line = file.readline()
        data_start = file.tell()

    feature_headers = [
        name.strip().lower()
        for name in parse_csv_line(header_line)
    ]

    if "split" not in feature_headers:
        raise ValueError("features.csv has no split column")

    split_column = feature_headers.index("split")
    file_size = os.stat(FEATURES_FILE)[6]

    if file_size <= data_start + 2:
        raise ValueError("features.csv has no data rows")

    print("Random replay ready. File size:", file_size)


def next_random_row():
    # Jump to a random byte position, skip the partial line, read the
    # next full line. Retry until it is a TEST row not used recently.
    global recent_offsets

    with open(FEATURES_FILE, "r") as file:
        for attempt in range(300):
            position = random.randint(data_start - 1, file_size - 2)

            file.seek(position)
            file.readline()

            line_start = file.tell()
            line = file.readline()

            if not line.strip():
                continue

            values = parse_csv_line(line)

            if len(values) < len(feature_headers):
                continue

            if values[split_column].lower() != "test":
                continue

            if line_start in recent_offsets and attempt < 250:
                continue

            recent_offsets.append(line_start)

            if len(recent_offsets) > 60:
                recent_offsets = recent_offsets[-60:]

            row = {}

            for index, name in enumerate(feature_headers):
                row[name] = values[index]

            return row

    raise ValueError("No test rows found in features.csv")


# ---------- Baselines ----------

def load_baselines():
    global baselines

    baselines = {}

    with open(BASELINE_FILE, "r") as file:
        header = parse_csv_line(file.readline())

        index = {
            name.lower(): position
            for position, name in enumerate(header)
        }

        for name in (
            "asset_id", "sensor", "baseline_rms"
        ):
            if name not in index:
                raise ValueError(
                    "Missing baseline column: " + name
                )

        for line in file:
            if not line.strip():
                continue

            values = parse_csv_line(line)

            try:
                key = group_key(
                    values[index["asset_id"]],
                    values[index["sensor"]],
                )

                baseline = number_or_none(
                    values[index["baseline_rms"]]
                )

                if baseline is not None and baseline > 0:
                    baselines[key] = {
                        "baseline_rms": baseline
                    }

            except (IndexError, ValueError):
                continue

    if not baselines:
        raise ValueError("No valid baselines found")

    print("Baselines loaded:", len(baselines))


# ---------- Precomputed thresholds ----------

def load_thresholds():
    global thresholds

    thresholds = {}

    print("\nLoading precomputed thresholds...")

    with open(THRESHOLDS_FILE, "r") as file:
        header = parse_csv_line(file.readline())

        index = {
            name.lower(): position
            for position, name in enumerate(header)
        }

        required = [
            "asset_id",
            "sensor",
            "observe_ratio",
            "inspect_ratio",
            "normal_count",
        ]

        for name in required:
            if name not in index:
                raise ValueError(
                    "Missing threshold column: " + name
                )

        for line in file:
            if not line.strip():
                continue

            values = parse_csv_line(line)

            try:
                key = group_key(
                    values[index["asset_id"]],
                    values[index["sensor"]],
                )

                observe = number_or_none(
                    values[index["observe_ratio"]]
                )

                inspect = number_or_none(
                    values[index["inspect_ratio"]]
                )

                count = int(
                    values[index["normal_count"]]
                )

                if (
                    observe is None
                    or inspect is None
                    or observe < 0
                    or inspect < observe
                    or count < 20
                ):
                    print("Skipping invalid threshold:", key)
                    continue

                thresholds[key] = {
                    "observe": observe,
                    "inspect": inspect,
                    "normal_samples": count,
                }

            except (ValueError, IndexError) as exc:
                print("Skipping malformed threshold:", exc)

    if not thresholds:
        raise ValueError("No valid thresholds loaded")

    print("Threshold groups loaded:", len(thresholds))

    for key in sorted(thresholds):
        item = thresholds[key]

        print(
            "Asset:", key[0],
            "| Sensor:", key[1],
            "| N:", item["normal_samples"],
            "| OBSERVE >=", round(item["observe"], 4),
            "| INSPECT >=", round(item["inspect"], 4),
        )


# ---------- Validation and classification ----------

def validate_measurement(row):
    required = [
        "rms",
        "peak_to_peak",
        "kurtosis",
        "crest_factor",
        "rpm",
        "sampling_rate",
    ]

    for field in required:
        if number_or_none(row.get(field)) is None:
            return False, "Missing/invalid " + field

    if number_or_none(row.get("rms")) < 0:
        return False, "Negative RMS"

    if number_or_none(row.get("peak_to_peak")) < 0:
        return False, "Negative peak-to-peak"

    if number_or_none(row.get("rpm")) <= 0:
        return False, "Invalid RPM"

    if number_or_none(row.get("sampling_rate")) <= 0:
        return False, "Invalid sampling rate"

    return True, ""


def classify_row(row):
    # Ground-truth label is not used for the decision.

    valid, reason = validate_measurement(row)

    if not valid:
        return {
            "status": "INVALID_DATA",
            "valid": False,
            "reason": reason,
            "rms_ratio": None,
            "observe_threshold": None,
            "inspect_threshold": None,
        }

    key = group_key(
        row.get("asset_id", ""),
        row.get("sensor", ""),
    )

    if key not in baselines:
        return {
            "status": "NO_BASELINE",
            "valid": False,
            "reason": "No baseline for asset/sensor",
            "rms_ratio": None,
            "observe_threshold": None,
            "inspect_threshold": None,
        }

    if key not in thresholds:
        return {
            "status": "NO_THRESHOLD",
            "valid": False,
            "reason": "No threshold for asset/sensor",
            "rms_ratio": None,
            "observe_threshold": None,
            "inspect_threshold": None,
        }

    rms = number_or_none(row.get("rms"))
    baseline = baselines[key]["baseline_rms"]
    ratio = rms / baseline

    limits = thresholds[key]

    if ratio >= limits["inspect"]:
        status = "INSPECT"
    elif ratio >= limits["observe"]:
        status = "OBSERVE"
    else:
        status = "NORMAL"

    return {
        "status": status,
        "valid": True,
        "reason": "",
        "rms_ratio": ratio,
        "observe_threshold": limits["observe"],
        "inspect_threshold": limits["inspect"],
    }


# ---------- Test evaluation ----------

def evaluate_test_split():
    normal_total = 0
    normal_alerts = 0
    fault_total = 0
    fault_detected = 0
    fault_inspect = 0
    excluded = 0
    unavailable = 0

    print("\nEvaluating TEST split...")

    for row in iter_feature_rows("test"):
        label = label_or_none(row.get("label"))

        if label == -1 or label is None:
            excluded += 1
            continue

        result = classify_row(row)

        if not result["valid"]:
            unavailable += 1
            continue

        status = result["status"]

        if label == 0:
            normal_total += 1

            if status in ("OBSERVE", "INSPECT"):
                normal_alerts += 1

        elif label in (1, 2, 3):
            fault_total += 1

            if status in ("OBSERVE", "INSPECT"):
                fault_detected += 1

            if status == "INSPECT":
                fault_inspect += 1

    print("\n===== TEST SPLIT EVALUATION =====")
    print("Excluded labels:", excluded)
    print("Unavailable decisions:", unavailable)

    if normal_total:
        print(
            "Normal cases:", normal_total,
            "| False alarms:", normal_alerts,
            "| False alarm rate:",
            round(100 * normal_alerts / normal_total, 2), "%"
        )
    else:
        print("No evaluable normal cases")

    if fault_total:
        print(
            "Fault cases:", fault_total,
            "| Detected:", fault_detected,
            "| Detection rate:",
            round(100 * fault_detected / fault_total, 2), "%"
        )

        print(
            "INSPECT:", fault_inspect,
            "| INSPECT rate:",
            round(100 * fault_inspect / fault_total, 2), "%"
        )
    else:
        print("No evaluable fault cases")

    print("=================================\n")


# ---------- LEDs and buzzer ----------

def indicate_status(status):
    buzzer.off()

    if status == "NORMAL":
        green_led.on()
        red_led.off()

    elif status in ("OBSERVE", "INSPECT"):
        green_led.off()
        red_led.on()

        if status == "INSPECT":
            buzzer.on()
            time.sleep_ms(120)
            buzzer.off()

    else:
        green_led.off()
        red_led.on()


# ---------- Network ----------

def connect_wifi(timeout_s=20):
    wlan.active(True)

    if wlan.isconnected():
        return True

    print("Connecting to Wi-Fi...")

    try:
        # Reset any half-finished attempt before trying again.
        try:
            wlan.disconnect()
        except Exception:
            pass

        # Channel 6 makes Wokwi-GUEST connect much faster.
        try:
            wlan.connect(WIFI_SSID, WIFI_PASSWORD, 6)
        except TypeError:
            wlan.connect(WIFI_SSID, WIFI_PASSWORD)

        for _ in range(timeout_s * 2):
            if wlan.isconnected():
                print("Wi-Fi connected:", wlan.ifconfig()[0])
                return True

            time.sleep_ms(500)

    except Exception as exc:
        print("Wi-Fi error:", exc)

    print("Wi-Fi connection failed")
    return False


def ensure_wifi():
    # Retries at most once every 10 s, so a failed connection does
    # not block the whole program on every single row.
    global last_wifi_attempt

    if wlan.isconnected():
        return True

    now = time.ticks_ms()

    if (
        last_wifi_attempt != 0
        and time.ticks_diff(now, last_wifi_attempt) < 10000
    ):
        return False

    last_wifi_attempt = now
    return connect_wifi()


def connect_mqtt():
    global mqtt_client, last_mqtt_attempt

    if MQTTClient is None:
        print("MQTT library unavailable")
        return False

    if not wlan.isconnected():
        return False

    try:
        client_id = "triage-replay-%06x" % random.getrandbits(24)

        mqtt_client = MQTTClient(
            client_id,
            MQTT_HOST,
            port=MQTT_PORT,
            keepalive=60,
        )

        mqtt_client.connect()

        # A dead connection now fails in 5 s instead of hanging.
        try:
            mqtt_client.sock.settimeout(5)
        except Exception:
            pass

        print("MQTT connected:", MQTT_HOST)
        return True

    except Exception as exc:
        print("MQTT connection failed:", exc)
        mqtt_client = None
        last_mqtt_attempt = time.ticks_ms()
        return False


def ensure_mqtt():
    global last_mqtt_attempt

    if not ensure_wifi():
        return False

    if mqtt_client is not None:
        return True

    now = time.ticks_ms()

    if time.ticks_diff(now, last_mqtt_attempt) < 2000:
        return False

    last_mqtt_attempt = now
    return connect_mqtt()


def publish_json(topic, payload):
    global mqtt_client

    message = json.dumps(payload)

    # Try twice: if the connection was dropped, reconnect
    # immediately and resend instead of losing the message.
    for _ in range(2):
        if mqtt_client is None:
            if not connect_mqtt():
                return False

        try:
            mqtt_client.publish(topic, message)
            return True

        except Exception as exc:
            print("MQTT publish failed:", exc)

            try:
                mqtt_client.disconnect()
            except Exception:
                pass

            mqtt_client = None

    return False


# ---------- Dataset replay ----------

def publish_row(row):
    global sequence_number

    sequence_number += 1

    asset_id = row.get("asset_id", "")
    sensor = row.get("sensor", "")

    device_id = (
        "asset-" + str(asset_id)
        + "-" + str(sensor)
        + "-muhammeedd1"
    )

    result = classify_row(row)
    indicate_status(result["status"])

    payload = {
        "device_id": device_id,
        "asset_id": asset_id,
        "sensor": sensor,
        "signal_index": row.get("signal_index"),
        "timestamp_ms": time.ticks_ms(),
        "source": "dataset_replay",
        "unit": "unknown",
        "sampling_rate_hz": number_or_none(
            row.get("sampling_rate")
        ),
        "rpm": number_or_none(row.get("rpm")),
        "features": {
            "rms": number_or_none(row.get("rms")),
            "peak_to_peak": number_or_none(
                row.get("peak_to_peak")
            ),
            "kurtosis": number_or_none(
                row.get("kurtosis")
            ),
            "crest_factor": number_or_none(
                row.get("crest_factor")
            ),
        },
        "valid": result["valid"],
        "triage_preview": {
            "status": result["status"],
            "rms_ratio": result["rms_ratio"],
            "observe_threshold": result["observe_threshold"],
            "inspect_threshold": result["inspect_threshold"],
            "reason": result["reason"],
        },
        "ground_truth_label": label_or_none(
            row.get("label")
        ),
        "split": row.get("split"),
    }

    ratio = result["rms_ratio"]

    print(
        "Row:", sequence_number,
        "| Asset:", asset_id,
        "| Sensor:", sensor,
        "| RMS:", row.get("rms"),
        "| Ratio:",
        round(ratio, 4) if ratio is not None else "N/A",
        "| Decision:", result["status"],
    )

    features_topic = (
        TOPIC_ROOT + "/" + device_id + "/features"
    )

    status_topic = (
        TOPIC_ROOT + "/" + device_id + "/status"
    )

    if ensure_mqtt():
        publish_json(features_topic, payload)

        publish_json(
            status_topic,
            {
                "device_id": device_id,
                "state": "online",
                "source": "dataset_replay",
                "timestamp_ms": time.ticks_ms(),
            },
        )


# ---------- Main ----------

def run():
    print("\nMaintenance Triage Assistant")
    print("Mode: pre-calibrated dataset replay")
    print("MQTT:", MQTT_HOST)

    load_baselines()
    load_thresholds()

    if RANDOM_REPLAY:
        init_random_replay()

    # Optional and slow: runs before connecting so the MQTT
    # keepalive is not wasted while the evaluation is running.
    if EVALUATE_ON_BOOT:
        evaluate_test_split()

    connect_wifi()
    connect_mqtt()

    # Seed after the network step so the random order differs per run.
    random.seed(time.ticks_us() ^ time.ticks_ms())

    while True:
        # Do not consume rows while offline; wait for the connection.
        if not ensure_mqtt():
            print("Offline - waiting for Wi-Fi/MQTT...")
            time.sleep_ms(1000)
            continue

        if RANDOM_REPLAY:
            publish_row(next_random_row())
            time.sleep_ms(REPLAY_INTERVAL_MS)
            continue

        rows_found = False

        for row in iter_feature_rows("test"):
            rows_found = True
            publish_row(row)
            time.sleep_ms(REPLAY_INTERVAL_MS)

        if not rows_found:
            raise ValueError("No test rows found in features.csv")

        print("Test replay completed; restarting...")
        time.sleep_ms(1000)


try:
    run()

except Exception as exc:
    print("FATAL ERROR:", exc)

    green_led.off()
    red_led.on()
    buzzer.off()

    if mqtt_client is not None:
        try:
            mqtt_client.disconnect()
        except Exception:
            pass