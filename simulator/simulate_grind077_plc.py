"""
Legacy S7-300 grinding cell simulator — the "hard problem" device.

Unlike simulate_ie_cnc.py, this machine has no IE Databus and no friendly
tag names. It's a raw S7-300 PLC, read via cryptic absolute addresses, with
its own ad-hoc units and representations:

  - Tag names are PLC addresses (DB10.DBD4, MW102, M20.1, ...), not semantic
    names — nothing here says "this is motor speed."
  - Units don't match the canonical profile: load is a scaled integer
    (raw = percent * 10), temperature is Fahrenheit, OEE is a 0..1 fraction,
    running status is a raw 0/1 integer, not a boolean.
  - The fault code space is this device's own — a different taxonomy than
    CNC-001's, which is fine: the shared profile only guarantees "an
    integer, 0 = no fault," not what the nonzero values mean.

ontology/bindings/grind077_binding.json declares, per canonical profile
property, which raw tag to read and what transform reconciles it. Nothing
in this file knows about the ontology — that's the point: the profile and
binding normalize this device from the outside, without touching the PLC.

  PUBLISH_MODE=console (default for this device)
      Prints payloads to stdout only — no Azure/AIO dependency.
  PUBLISH_MODE=mqtt
      Publishes to the AIO MQTT Broker on topic s7/grind077.
      export MQTT_HOST=<broker ip>
  PUBLISH_MODE=eventhub
      Publishes directly to Azure Event Hub.
      export EH_CONNECTION_STRING="Endpoint=sb://..."

Optional overrides:
    PUBLISH_INTERVAL=3 MACHINE_ID=GRIND-078 python simulate_grind077_plc.py
"""
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# ── Config ────────────────────────────────────────────────────────────────────
PUBLISH_MODE       = os.environ.get("PUBLISH_MODE", "console").lower()
CONNECTION_STRING  = os.environ.get("EH_CONNECTION_STRING")
EVENTHUB_NAME      = os.environ.get("EH_NAME", "plc-telemetry")
MQTT_HOST          = os.environ.get("MQTT_HOST", "")
MQTT_PORT          = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TOPIC         = os.environ.get("MQTT_TOPIC", "s7/grind077")
PUBLISH_INTERVAL   = float(os.environ.get("PUBLISH_INTERVAL", "5"))
MACHINE_ID         = os.environ.get("MACHINE_ID", "GRIND-077")

if PUBLISH_MODE == "eventhub":
    from azure.eventhub import EventHubProducerClient, EventData
    if not CONNECTION_STRING:
        raise SystemExit("Set EH_CONNECTION_STRING to the Event Hub connection string.\n")
elif PUBLISH_MODE == "mqtt":
    import paho.mqtt.client as mqtt
    if not MQTT_HOST:
        raise SystemExit("Set MQTT_HOST to the AIO broker IP.\n")
elif PUBLISH_MODE == "console":
    pass
else:
    raise SystemExit(f"Unknown PUBLISH_MODE={PUBLISH_MODE!r}. Use 'eventhub', 'mqtt', or 'console'.")

_tick       = 0
_part_count = random.randint(4000, 9000)
_fault_cooldown = 0


def _next_raw_values() -> dict:
    """Raw S7 tags, exactly as the PLC would expose them — no semantic naming."""
    global _tick, _part_count, _fault_cooldown
    _tick += 1

    wheel_rpm    = 2950 + 80 * random.uniform(-1, 1) + 15 * (_tick % 7)
    load_pct     = 38 + random.uniform(-6, 6)
    feed_mm_min  = 180 + random.uniform(-20, 20)
    temp_f       = 100 + load_pct * 0.35 + random.uniform(-2, 2)   # Fahrenheit
    oee_fraction = min(0.98, max(0.55, 0.86 + random.uniform(-0.05, 0.05)))
    running      = 1 if wheel_rpm > 200 else 0

    if _tick % 12 == 0 and running:
        _part_count += 1

    if _fault_cooldown > 0:
        fault = 302
        _fault_cooldown -= 1
    elif random.random() < 0.025:
        fault = random.choice([301, 302, 309])
        _fault_cooldown = 2
    else:
        fault = 0

    return {
        "DB10.DBD4":  round(wheel_rpm, 1),          # motor speed, RPM (matches profile unit)
        "MW102":      round(load_pct * 10),          # load, scaled int = pct * 10
        "DB10.DBD8":  round(feed_mm_min, 0),         # feed rate, mm/min (matches profile unit)
        "DB10.DBD12": round(temp_f, 1),              # wheel temp, Fahrenheit
        "DB20.DBW0":  _part_count,                    # part count (matches profile unit)
        "DB10.DBW20": fault,                          # fault code, device-local taxonomy
        "M20.1":      running,                        # running status, raw 0/1 int
        "DB30.DBD0":  round(oee_fraction, 3),         # OEE, 0..1 fraction
    }


def build_raw_payload() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return json.dumps({
        "timestamp": ts,
        "source":    "s7://192.168.10.44/rack0/slot2",
        "device":    MACHINE_ID,
        **_next_raw_values(),
    })


def main():
    print(f"S7-300 Grinding Cell Simulator — machine: {MACHINE_ID}")
    print(f"Publish mode: {PUBLISH_MODE.upper()}")
    print("Raw PLC tags only — no semantic names, no shared units. See")
    print("ontology/bindings/grind077_binding.json for the reconciliation.")
    print(f"Interval: {PUBLISH_INTERVAL}s   |   Ctrl+C to stop\n")

    if PUBLISH_MODE == "mqtt":
        _run_mqtt()
    elif PUBLISH_MODE == "eventhub":
        _run_eventhub()
    else:
        _run_console()


def _run_console():
    try:
        while True:
            payload = build_raw_payload()
            print(f"  -> {payload}")
            time.sleep(PUBLISH_INTERVAL)
    except KeyboardInterrupt:
        print("\nSimulator stopped.")


def _run_mqtt():
    import paho.mqtt.client as mqtt
    print(f"Target MQTT broker: {MQTT_HOST}:{MQTT_PORT}  topic: {MQTT_TOPIC}")
    client = mqtt.Client(client_id=f"grind-plc-sim-{MACHINE_ID}")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    try:
        while True:
            payload = build_raw_payload()
            result = client.publish(MQTT_TOPIC, payload, qos=1)
            result.wait_for_publish()
            print(f"  -> [{MQTT_TOPIC}] {payload}")
            time.sleep(PUBLISH_INTERVAL)
    except KeyboardInterrupt:
        print("\nSimulator stopped.")
    finally:
        client.loop_stop()
        client.disconnect()


def _run_eventhub():
    from azure.eventhub import EventHubProducerClient, EventData
    print(f"Target Event Hub: {EVENTHUB_NAME}")
    producer = EventHubProducerClient.from_connection_string(
        conn_str=CONNECTION_STRING, eventhub_name=EVENTHUB_NAME,
    )
    try:
        while True:
            payload = build_raw_payload()
            batch = producer.create_batch()
            event = EventData(payload)
            event.properties = {"content-type": "application/json", "source": "s7/grind077", "machine-id": MACHINE_ID}
            batch.add(event)
            producer.send_batch(batch)
            print(f"  -> {payload}")
            time.sleep(PUBLISH_INTERVAL)
    except KeyboardInterrupt:
        print("\nSimulator stopped.")
    finally:
        producer.close()


if __name__ == "__main__":
    main()
