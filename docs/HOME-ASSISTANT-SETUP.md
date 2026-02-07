# Home Assistant Setup for Frigate-OpenClaw Bridge

**HA Server:** 192.168.1.20
**MQTT Broker:** 192.168.1.20:1885

The bridge publishes AI analysis results to MQTT topic `openclaw/frigate/analysis`.
Add the following to your Home Assistant configuration to consume these.

---

## Step 1: MQTT Sensor

Add to `configuration.yaml` (or your MQTT sensors file):

```yaml
mqtt:
  sensor:
    - name: "Frigate AI Analysis"
      state_topic: "openclaw/frigate/analysis"
      value_template: "{{ value_json.camera }}"
      json_attributes_topic: "openclaw/frigate/analysis"
      json_attributes_template: "{{ value_json | tojson }}"
      icon: mdi:cctv

    - name: "Frigate AI Analysis Text"
      state_topic: "openclaw/frigate/analysis"
      value_template: "{{ value_json.analysis[:250] }}"
      icon: mdi:text-box-outline

    - name: "Frigate AI Last Camera"
      state_topic: "openclaw/frigate/analysis"
      value_template: "{{ value_json.camera }}"
      icon: mdi:camera

    - name: "Frigate AI Timestamp"
      state_topic: "openclaw/frigate/analysis"
      value_template: "{{ value_json.timestamp }}"
      device_class: timestamp
      icon: mdi:clock-outline
```

After adding, restart HA or reload MQTT entities from **Developer Tools → YAML → MQTT entities**.

---

## Step 2: Automation (Optional)

Example automation that sends an HA notification **immediately**, then **updates** it when the AI analysis arrives:

```yaml
automation:
  - alias: "Frigate AI Alert Notification"
    trigger:
      - platform: mqtt
        topic: "openclaw/frigate/analysis"
    action:
      - service: notify.notify
        data:
          title: "Security: {{ trigger.payload_json.camera }}"
          message: "{{ trigger.payload_json.analysis }}"
          data:
            image: "{{ trigger.payload_json.snapshot_path }}"
            tag: "frigate-{{ trigger.payload_json.event_id }}"
```

---

## Step 3: Alexa Announcement (Alexa Media Player)

Announce security alerts on your Echo devices when a person is detected.

Create this automation via **Settings → Automations → Create** or add to `automations.yaml`:

```yaml
- alias: "Frigate AI Alexa Announcement"
  trigger:
    - platform: mqtt
      topic: "openclaw/frigate/analysis"
  action:
    - service: notify.alexa_media
      data:
        message: >-
          Security alert from {{ trigger.payload_json.camera }}.
          {{ trigger.payload_json.analysis }}
        target:
          - media_player.ravi_s_echo_dot
          - media_player.echo_show_5
          - media_player.ravi_s_old_echo_dot
          - media_player.mom_s_echo
        data:
          type: announce
```

---

## Step 4: Lovelace Card (Optional)

Add a card to your dashboard to show the latest analysis:

```yaml
type: entities
title: Frigate AI Security
entities:
  - entity: sensor.frigate_ai_last_camera
    name: Camera
  - entity: sensor.frigate_ai_analysis_text
    name: Analysis
  - entity: sensor.frigate_ai_timestamp
    name: Last Alert
```

Or a more detailed Markdown card:

```yaml
type: markdown
title: Last Security Alert
content: >
  **Camera:** {{ state_attr('sensor.frigate_ai_analysis', 'camera') }}

  **Time:** {{ states('sensor.frigate_ai_timestamp') }}

  {{ state_attr('sensor.frigate_ai_analysis', 'analysis') }}
```

---

## Verifying MQTT Messages

In HA, go to **Developer Tools → MQTT → Listen to a topic** and subscribe to:

```
openclaw/frigate/analysis
```

Then trigger a detection (walk in front of a camera). You should see:
- A **pending** payload within ~2-5 seconds
- A **final analysis** payload within ~15-40 seconds

---

## Payload Reference

```json
{
  "camera": "Tapo-GarageCam",
  "label": "person",
  "analysis": "[GarageCam] Threat: LOW\nOne person in casual clothes...",
  "timestamp": "2026-02-07T08:30:00+00:00",
  "event_id": "1738920600.123456-abc123",
  "snapshot_path": "/home/<HOME_USER>/frigate/storage/ai-snapshots/..."
}
```
