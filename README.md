<div dir="rtl">

# Maintenance Triage Assistant

> Vibration ← features ← MQTT ← قواعد الـ triage ← inspection queue مرتبة ← dashboard ← إجراء الفني

---

## فكرة المشروع

الـ vibration alarm العادي بيقول للفني إن "فيه اهتزاز"، لكنه مش بيقول هل الماكينة محتاجة **فحص فوري (inspection)** ولا **مراقبة مستمرة (observation)** بس. المشروع ده بيحوّل قياسات الاهتزاز لـ **inspection queue مرتبة بالأولوية**، والفني يقدر يعمل عليها Acknowledge.

- **المستخدمين المستهدفين:** الورش الصغيرة ومهندسو الصيانة.
- **الفكرة الأساسية:** كل قراءة اهتزاز بتتقارن بالـ baseline (السلوك الطبيعي) لنفس الماكينة ونفس الـ sensor، وبعدها بنحدد الـ status (`NORMAL` أو `OBSERVE` أو `INSPECT`)، والـ alerts بتتحفظ في queue دائمة ومرتبة.

مسار البيانات المقصود من الأول للآخر:

</div>

<div dir="ltr">

```
Vibration source (ESP32 simulation / dataset replay)
      -> MQTT broker
      -> Backend: validation + baseline comparison + triage rules
      -> Persistent inspection queue (SQLite)
      -> Node-RED dashboard
      -> Technician acknowledges the alert
```

</div>

<div dir="rtl">

---

## الوضع الحالي (اقرأه الأول)

الـ repository ده فيه حاليًا **قلب المعالجة (processing core) وبيشتغل offline على dataset محفوظة**. هو **مش** نظام live: مفيش هنا أي اتصال بـ sensor ولا ESP32 ولا MQTT broker لحد دلوقتي.

| الجزء | المسؤول | الحالة |
|---|---|---|
| Feature extraction والـ baseline وقواعد الـ triage والـ inspection queue (الـ repo ده) | الـ Backend والـ triage (محمد) | خلص، offline |
| Node-RED dashboard | صاحب الـ dashboard | مذكور إنها شبه خلصانة، ولسه ما اتراجعتش هنا |
| ESP32 simulation | صاحب الـ simulation | مذكور إنها شغالة لوحدها، ولسه ما اتراجعتش هنا |
| الـ MQTT broker والـ topics وشكل الـ messages | الفريق كله | **لسه ما اتفقناش** (فيه اقتراح تحت) |
| Live backend (subscriber على MQTT بيشغّل قواعد الـ triage) | الـ Backend | لسه ما بدأش |
| Dataset replay publisher | يتحدد بعدين | لسه ما بدأش |
| End-to-end tests | الفريق كله | لسه ما بدأتش |

---

## محتويات الـ repository

| الملف | بيعمل إيه |
|---|---|
| `summarize_sca.py` | بيطبع بنية ملفات الـ `.mat` (fields وshapes وsampling rates وعدد كل label). بيتشغّل مرة واحدة علشان نفهم الـ dataset. |
| `extract_features.py` | بيحسب **RMS وpeak-to-peak وkurtosis وcrest factor** لكل signal، ويكتب `data/features.csv`. |
| `triage.py` | بيبني baseline لكل asset وsensor، ويحسب `rms_ratio`، ويحدد الـ status والـ priority. بيكتب `data/baseline.csv` و`data/triage_results.csv`. |
| `queue_manager.py` | بيحفظ alerts الـ `OBSERVE` و`INSPECT` في SQLite، ويعرضها بالأولوية، ويسجل Acknowledge الفني. بيكتب `data/inspection_queue.db`. |
| `inspect_data.py` | script أقدم لفحص الـ dataset، موجود للرجوع إليه. |

الـ dataset نفسها **مش مرفوعة** على الـ repository.

---

## قواعد الـ triage بتشتغل إزاي

1. **الـ Baseline:** لكل `(asset_id, sensor)` بناخد الـ median لقيم الـ RMS للسجلات بتاعة الـ train اللي الـ label بتاعها `0`.
2. **الـ Ratio:** `rms_ratio = rms / baseline_rms`.
3. **القرار:**

| الشرط | الـ status | الـ priority |
|---|---|---|
| الـ label بتساوي `-1` | `EXCLUDED` | 5 |
| مفيش baseline | `NO_BASELINE` | 4 |
| `rms_ratio >= 2.0` | `INSPECT` | 1 |
| `rms_ratio >= 1.5` | `OBSERVE` | 2 |
| غير كده | `NORMAL` | 3 |

الـ queue فيها `OBSERVE` و`INSPECT` بس، مرتبة بالـ priority وبعدها بأعلى ratio.

> **مهم:** القيمتين `OBSERVE_RATIO = 1.5` و`INSPECT_RATIO = 2.0` هما **قيم تجريبية للعرض بس، مش حدود أمان متحقق منها** لأي ماكينة حقيقية.

---

## نتايج آخر تشغيل offline

دي نتايج تشغيل واحد، مش مخرجات مضمونة في كل مرة.

| الـ status | عدد السجلات |
|---|---|
| `NORMAL` | 5048 |
| `OBSERVE` | 418 |
| `INSPECT` | 980 |
| `EXCLUDED` | 198 |
| **الإجمالي** | **6644** |

الـ queue كان فيها **1398** alert (980 + 418)، واحد منهم اتعمله Acknowledge. كتير من سجلات الـ `INSPECT` الـ label بتاعها `0`، ومعنى الـ labels في الـ dataset مش موثق هنا، فالقواعد محتاجة calibration قبل ما حد يعتمد عليها.

---

## عقد التكامل المقترح (Integration contract)

الجزء ده **اقتراح** بس، ومفيش منه حاجة موجودة في الكود لسه. الاتفاق عليه هو أول مهمة للفريق، لأن الـ dashboard والـ simulation والـ backend كلهم معتمدين عليه.

| المكوّن | بيعمل Publish على | بيعمل Subscribe على |
|---|---|---|
| المصدر (ESP32 simulation أو dataset replay) | `triage/<device_id>/features` و`triage/<device_id>/status` | مفيش |
| الـ Backend (triage + queue) | `triage/<device_id>/result` | `triage/<device_id>/features` و`triage/<device_id>/ack` |
| الـ Dashboard (Node-RED) | `triage/<device_id>/ack` | `triage/<device_id>/result` و`triage/<device_id>/status` |

**رسالة الـ features (من المصدر للـ backend):**

</div>

<div dir="ltr">

```json
{
  "device_id": "rig-01",
  "timestamp": "2026-10-11T19:30:00Z",
  "sensor": "DS",
  "unit": "TBD",
  "sampling_rate_hz": 5120,
  "features": { "rms": 0.24, "peak_to_peak": 1.1, "kurtosis": 3.0, "crest_factor": 4.2 },
  "valid": true,
  "source": "dataset_replay"
}
```

</div>

<div dir="rtl">

- `source`: بتكون `esp32_sim` أو `dataset_replay` أو `esp32_real`. ممنوع البيانات المحاكاة (simulated) تبان كأنها قياس فيزيائي حقيقي.
- `unit`: لسه مش متأكدة. بتتاخد من حقل `unit` في الـ dataset أو من الـ sensor نفسه.
- `valid: false`: معناها إن المصدر نفسه عارف إن القراءة بايظة (بيانات ناقصة أو غير صالحة).

**رسالة الـ result (من الـ backend للـ dashboard):**

</div>

<div dir="ltr">

```json
{
  "device_id": "rig-01", "sensor": "DS", "timestamp": "2026-10-11T19:30:00Z",
  "rms": 10.55, "baseline_rms": 0.113, "rms_ratio": 93.37,
  "status": "INSPECT", "priority": 1, "alert_id": 42, "acknowledged": false
}
```

</div>

<div dir="rtl">

**رسالة الـ ack (من الـ dashboard للـ backend):**

</div>

<div dir="ltr">

```json
{ "alert_id": 42, "technician": "Technician 1", "timestamp": "2026-10-11T19:35:00Z" }
```

</div>

<div dir="rtl">

**توفر الجهاز (Device availability):** المصدر بيضبط MQTT Last Will على `triage/<device_id>/status` وبينشر heartbeat بشكل دوري. الـ dashboard بتعرض الجهاز على إنه **unavailable** لو حالته offline، أو لو مفيش أي message وصلت خلال timeout معين (قيمته لسه هتتحدد). ومينفعش أبدًا قراءة قديمة (stale) تتعرض على إنها live.

---

## المطلوب من كل واحد في الفريق

### صاحب الـ Dashboard (Node-RED)

1. كمّل تصميم الـ layout. مش محتاج الـ backend دلوقتي: استخدم Inject nodes برسالة الـ *result* اللي فوق.
2. اعرض لكل جهاز: الـ availability، وآخر features، والـ baseline والـ `rms_ratio`، والـ status والـ priority، ووقت الـ alert.
3. ضيف زرار **Acknowledge** بينشر رسالة الـ *ack*. الـ dashboard بتعرض وبتبعت actions بس، ومينفعش تعيد تنفيذ قواعد الـ triage بنفسها.
4. قول للفريق بتستخدم أنهي MQTT broker وإيه الـ host والـ port.

### صاحب الـ ESP32 simulation

1. انشر رسالة الـ *features* مع `source: "esp32_sim"`.
2. علشان الـ simulation تشتغل على **الـ dataset الحقيقية**، اعمل replay لصفوف من `data/features.csv`. استخدم `device_id` بيقابل `asset_id` و`sensor` حقيقيين، لأن الـ baselines موجودة بس للـ assets والـ sensors اللي في `data/baseline.csv`، وغير كده الـ backend هيرجّع `NO_BASELINE`.
3. جهّز أربع سيناريوهات: stable، وtransient spike قصير، وsustained deviation، وبيانات ناقصة أو غير صالحة (`valid: false` أو انقطاع الـ messages).
4. اتفق مع صاحب الـ backend: الـ ESP32 هو اللي يحسب الـ features ولا يبعتها محسوبة جاهزة؟ الـ backend محتاج نفس تعريفات الـ features الأربعة اللي في `extract_features.py`.

### صاحب الـ Backend (الـ repository ده)

1. فصل قواعد `triage.py` في functions صغيرة تقبل **قراءة واحدة** بدل ملف CSV كامل.
2. كتابة MQTT subscriber بيتحقق من الـ message، ويحمّل الـ baseline، ويطبق نفس الـ thresholds، ويحدّث الـ queue.
3. تغيير هوية الـ alert من `(asset_id, sensor, split, signal_index)` لهوية تناسب البيانات الـ live، وإضافة حالة `resolved`، وعدم مسح الـ alerts اللي اتعملها Acknowledge.
4. نشر رسالة الـ *result* ومعالجة رسالة الـ *ack*.

---

## الفرق بين Acknowledged وResolved

- **Acknowledged:** الفني شاف الـ alert وهيتابعه.
- **Resolved:** الفني فحص الماكينة وقفل المشكلة.

الـ queue الحالية بتدعم الـ Acknowledge بس.

---

## اختبارات القبول المقترحة (Acceptance tests)

دي مقترحة بس، ولسه ما اتنفذتش.

| # | السيناريو | المتوقع |
|---|---|---|
| 1 | قراءة عادية | `NORMAL` ومفيش alert |
| 2 | قراءة فوق الـ threshold | `OBSERVE` أو `INSPECT` والـ alert بتتخزن |
| 3 | Acknowledge للـ alert | `acknowledged = 1` مع الاسم والوقت |
| 4 | Restart للـ backend | الـ alert والـ acknowledgement يفضلوا موجودين |
| 5 | الجهاز وقف عن الـ publish | الـ dashboard تعرضه unavailable، مش آخر قراءة على إنها live |
| 6 | قراءة غير صالحة (`valid: false`) | تترفض من غير alert ويتسجل السبب |

سجّل لكل اختبار: الـ input والمتوقع والفعلي والوقت والنتيجة (pass أو fail).

---

## القيود المعروفة (Limitations)

- الـ thresholds تجريبية ومش متحقق منها.
- القرار حاليًا بيعتمد على RMS بس. الـ kurtosis والـ crest factor والـ peak-to-peak محسوبين بس مش مستخدمين.
- الـ baseline قيمة واحدة لكل asset وsensor، ومش بياخد الـ RPM ولا ظروف التشغيل في الاعتبار.
- معنى الـ labels في الـ dataset مش موثق هنا. الكود بيعتبر `-1` مستبعد، و`0` في الـ train هو مرجع الـ baseline بس.
- وحدة القياس (unit) لسه مش متأكدة.

---

## التشغيل (Setup)

</div>

<div dir="ltr">

```bash
pip install numpy pandas scipy
```

</div>

<div dir="rtl">

حط ملفات الـ `.mat` بتاعة الـ dataset تحت `data/sca/<asset_id>/` (مثلاً `data/sca/1/train.mat`)، وبعدين شغّل:

</div>

<div dir="ltr">

```bash
python summarize_sca.py      # optional: inspect the files
python extract_features.py
python triage.py
python queue_manager.py
```

</div>

<div dir="rtl">

علشان تعمل Acknowledge لـ alert:

</div>

<div dir="ltr">

```bash
python -c "from queue_manager import acknowledge; acknowledge(1, 'Technician 1')"
```

</div>
