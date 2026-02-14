# Phase 3.5 — Known Faces Recognition

Goal: Reduce unnecessary notifications by recognizing known people while still alerting on unusual behavior.

---

## What This Phase Adds

- Face recognition pipeline that labels a detection as `known_face` or `unknown_face`.
- Policy logic to suppress routine alerts for known people.
- “Unusual activity” checks so known people still trigger if behavior is suspicious.

---

## Why This Helps

- Stops alert fatigue when family or trusted people pass by cameras.
- Keeps security intact by still alerting on *behavior*, not just identity.

---

## Inputs / Outputs

**Inputs**
- Frigate event snapshot (already available)
- Camera name, time of day, zone
- Face database (enrolled images)

**Outputs**
- `known_face: true/false`
- `person_name: "Ravi"` or `unknown`
- `face_confidence: 0.00–1.00`

These outputs get merged into the existing MQTT payload so OpenClaw policy can act on them.

---

## Tools / Components Used

### Face Recognition Engine (choose one)

1. **InsightFace (recommended)**
   - Strong accuracy and speed on CPU.
   - Uses `buffalo_l` or `buffalo_s` model.
   - Python package: `insightface`, `onnxruntime`.

2. **face_recognition (simple but slower)**
   - Easy to use, lower accuracy.
   - CPU‑only, can be slow on old laptops.
   - Python package: `face_recognition` (depends on dlib).

3. **Frigate Face Recognition add‑ons**
   - If Frigate is extended with face recognition (community add‑ons), reuse their output.
   - This avoids duplicate face inference in the bridge.

---

## Data Storage

### Known Faces Database

- Store embeddings + labels in a JSON or SQLite file.
- Structure:

```
faces.db (SQLite)
  - person_id
  - name
  - embedding (vector)
  - created_at
```

or

```
faces.json
{
  "ravi": [0.11, 0.22, ...],
  "mom":  [0.05, 0.19, ...]
}
```

### Enrollment Folder

```
/home/<user>/frigate/known-faces/
  ravi/
    img1.jpg
    img2.jpg
  mom/
    img1.jpg
```

---

## Implementation Steps (Detailed)

### 1. Add Face Recognition Stage to Bridge

- After snapshot download, run face detection + embedding.
- Compare embedding against known faces list.
- If distance < threshold, mark as known.

Suggested thresholds:
- InsightFace cosine: `0.30–0.45`
- face_recognition distance: `0.45–0.60`

### 2. Extend MQTT Payload

Add new fields:

```
"known_face": true,
"person_name": "Ravi",
"face_confidence": 0.83
```

### 3. Update OpenClaw Policy Prompt

Tell OpenClaw:

- If `known_face=true` and `risk=low`, suppress or downgrade notification.
- If `known_face=true` but unusual activity detected, still alert.

### 4. Add “Unusual Activity” Rules

Examples:

- Known person **outside normal hours** (e.g., 1 AM)
- Known person in **restricted zone**
- Known person **loitering too long**
- Known person **opening locks, windows, gates**

### 5. Maintain the Face DB

- Add new people with a script:

```
python3 scripts/enroll-face.py --name ravi --images /path/to/images
```

- Rebuild embeddings if new data added.

---

## Pros / Cons

**Pros**
- Big reduction in noisy alerts
- More trust in alerts that *do* come through

**Cons**
- Face recognition adds CPU load
- Requires enrollment & maintenance
- Potential privacy concerns

---

## Recommendation

This phase is **worth it** if:
- You’re getting frequent alerts from known people
- You want fewer false positives

Skip it if:
- Only a few alerts per day
- CPU is already maxed

---

## Where It Fits

- **After Phase 3 (Policy Layer)**
- **Before Phase 4 (Memory Store)**

Known‑face identity becomes a policy input, and the memory store can use it later for patterns and summaries.

