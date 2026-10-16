import time
import json
import threading
import ssl
import numpy as np
import pandas as pd
import paho.mqtt.client as mqtt
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

# ==========================================
# 🔴 MQTT + SSL CONFIGURATION (CREDENTIALS HERE) 🔴
# ==========================================
MQTT_BROKER = "fd6769c5c601470e9fe4932f0f479977.s1.eu.hivemq.cloud"  # غيّر هذا إلى رابط الكلاستر الخاص بك، مثلاً: xxx.s1.eu.hivemq.cloud
MQTT_PORT = 8883                   # منفذ 8883 مخصص للاتصالات المشفرة SSL/TLS
MQTT_USERNAME = "fathwi"                 # <--- ضع اسم المستخدم هنا
MQTT_PASSWORD = "Ahmad#1984"                 # <--- ضع كلمة المرور هنا
# ==========================================

MQTT_TELEMETRY_TOPIC = "digital_twin/motor/telemetry"
MQTT_CONTROL_TOPIC = "digital_twin/motor/control"

current_state = "healthy"
motor_running = True
latest_data = {}

# --- حساب خط الأساس (Baseline) من ملف healthy.csv ---
try:
    healthy_df = pd.read_csv("healthy.csv")
    
    # حساب محصلة الاهتزاز للمحاور الثلاثة
    baseline_vib = np.sqrt(healthy_df['ax_g']**2 + healthy_df['ay_g']**2 + healthy_df['az_g']**2)
    median_vib = np.median(baseline_vib)
    mad_vib = np.median(np.abs(baseline_vib - median_vib))
    if mad_vib == 0: mad_vib = 0.0001
    
    # حساب خط الأساس للحرارة (للأعطال مثل overheat)
    median_temp = np.median(healthy_df['temp_c'])
    mad_temp = np.median(np.abs(healthy_df['temp_c'] - median_temp))
    if mad_temp == 0: mad_temp = 0.0001
    
except Exception as e:
    print(f"Error loading healthy.csv: {e}")
    median_vib, mad_vib, median_temp, mad_temp = 0, 1, 0, 1

# --- إعدادات MQTT مع تفعيل SSL ---
client = mqtt.Client()
if MQTT_USERNAME and MQTT_PASSWORD:
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

# تفعيل التشفير (ضروري لـ HiveMQ Cloud)
client.tls_set(tls_version=ssl.PROTOCOL_TLS)

def on_connect(client, userdata, flags, rc):
    print("Connected to HiveMQ with result code "+str(rc))
    client.subscribe(MQTT_CONTROL_TOPIC)

def on_message(client, userdata, msg):
    global motor_running
    command = msg.payload.decode().lower()
    if command == "on":
        motor_running = True
    elif command == "off":
        motor_running = False

client.on_connect = on_connect
client.on_message = on_message
client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_start()

# --- حلقة المحاكاة الخلفية ---
def simulation_loop():
    global latest_data, current_state, motor_running
    while True:
        if motor_running:
            try:
                # قراءة صف عشوائي من ملف الـ CSV المحدد
                df = pd.read_csv(f"{current_state}.csv")
                sample = df.sample(1).iloc[0]
                
                ax, ay, az = sample["ax_g"], sample["ay_g"], sample["az_g"]
                temp = sample["temp_c"]
                rpm = sample["rpm"]
                
                # حساب محصلة الاهتزاز الحالية
                current_vib = np.sqrt(ax**2 + ay**2 + az**2)
                
                # تطبيق معادلة Z-score المطلوبة
                z_score_vib = (current_vib - median_vib) / (1.4826 * mad_vib)
                z_score_temp = (temp - median_temp) / (1.4826 * mad_temp)
                
                # نأخذ الانحراف الأكبر سواء في الاهتزاز أو الحرارة
                max_z_score = z_score_vib if abs(z_score_vib) > abs(z_score_temp) else z_score_temp
                
                # تحديث الحالة (عتبة الإنذار إذا زاد الانحراف عن 3 أضعاف الـ MAD)
                status = "HEALTHY" if abs(max_z_score) < 3 else "INSPECT ⚠️"
                
                latest_data = {
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "ax_g": round(ax, 4),
                    "ay_g": round(ay, 4),
                    "az_g": round(az, 4),
                    "vibration_mag": round(current_vib, 4),
                    "temperature": round(temp, 1),
                    "rpm": round(rpm, 1),
                    "z_score": round(max_z_score, 2),
                    "status": status,
                    "active_file": f"{current_state}.csv"
                }
                
                client.publish(MQTT_TELEMETRY_TOPIC, json.dumps(latest_data))
                
            except Exception as e:
                print(f"Error reading {current_state}.csv: {e}")
                
        time.sleep(1) # إرسال البيانات كل ثانية

threading.Thread(target=simulation_loop, daemon=True).start()

# --- مسارات واجهة المستخدم (Flask Routes) ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    return jsonify(latest_data)

@app.route('/api/set_state', methods=['POST'])
def set_state():
    global current_state
    current_state = request.json.get('state', 'healthy')
    return jsonify({"success": True, "state": current_state})

if __name__ == '__main__':
    app.run(debug=True, port=5000)