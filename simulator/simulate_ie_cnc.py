"""
Siemens Industrial Edge CNC simulator — sends to Azure Event Hub directly.

Mimics the payload format produced by the IE S7 Connector on the IE Databus
(topic: ie/cnc). Publishes directly to the demo Event Hub so data appears in
the PartnerPLCDemo / PlcTelemetry KQL table without needing the partner's setup.

Usage:
    pip install azure-eventhub
    export EH_CONNECTION_STRING="Endpoint=sb://eh-partner-plc-demo..."
    python simulate_ie_cnc.py

    # Demo mode — cycles through: Normal → Degrading → Fault → Recovering
    DEMO_MODE=true DEMO_CYCLE_MINUTES=30 python simulate_ie_cnc.py

    # Optional overrides:
    PUBLISH_INTERVAL=3 MACHINE_ID=CNC-002 python simulate_ie_cnc.py
"""
import json
import math
import os
import random
import time
from datetime import datetime, timezone

from azure.eventhub import EventHubProducerClient, EventData

# ── Config ────────────────────────────────────────────────────────────────────
CONNECTION_STRING  = os.environ.get("EH_CONNECTION_STRING")
EVENTHUB_NAME      = os.environ.get("EH_NAME", "plc-telemetry")
PUBLISH_INTERVAL   = float(os.environ.get("PUBLISH_INTERVAL", "5"))
MACHINE_ID         = os.environ.get("MACHINE_ID", "CNC-001")
DEMO_MODE          = os.environ.get("DEMO_MODE", "false").lower() == "true"
DEMO_CYCLE_SECONDS = int(os.environ.get("DEMO_CYCLE_MINUTES", "30")) * 60

if not CONNECTION_STRING:
    raise SystemExit(
        "Set EH_CONNECTION_STRING to the Event Hub connection string.\n"
        "Example:\n"
        "  export EH_CONNECTION_STRING='Endpoint=sb://eh-partner-plc-demo"
        ".servicebus.windows.net/;SharedAccessKeyName=...'\n"
    )

# ── Demo phase boundaries (fraction of cycle) ─────────────────────────────────
#   NORMAL     0.00 → 0.40  (12 min of 30)
#   DEGRADING  0.40 → 0.70  (9 min)  — tool temp rising, OEE dropping
#   FAULT      0.70 → 0.83  (4 min)  — machine stopped, overtemp alarm
#   RECOVERING 0.83 → 1.00  (5 min)  — restart, metrics climbing back
_PHASE_BOUNDS = [
    (0.00, "NORMAL"),
    (0.40, "DEGRADING"),
    (0.70, "FAULT"),
    (0.83, "RECOVERING"),
]

# ── State ─────────────────────────────────────────────────────────────────────
_tick       = 0
_part_count = random.randint(200, 600)
_fault_cooldown = 0
_start_time = time.monotonic()


def _current_phase() -> tuple[str, float]:
    """
    Returns (phase_name, phase_progress_0_to_1).
    phase_progress = how far through the current phase we are.
    """
    if not DEMO_MODE:
        return "NORMAL", 0.0

    elapsed   = (time.monotonic() - _start_time) % DEMO_CYCLE_SECONDS
    fraction  = elapsed / DEMO_CYCLE_SECONDS  # 0.0 → 1.0 within cycle

    phase_name  = "NORMAL"
    phase_start = 0.0
    for boundary, name in _PHASE_BOUNDS:
        if fraction >= boundary:
            phase_name  = name
            phase_start = boundary

    # Find the end boundary
    idx = [n for _, n in _PHASE_BOUNDS].index(phase_name)
    phase_end = _PHASE_BOUNDS[idx + 1][0] if idx + 1 < len(_PHASE_BOUNDS) else 1.0

    phase_progress = (fraction - phase_start) / max(0.001, phase_end - phase_start)
    return phase_name, min(1.0, max(0.0, phase_progress))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _next_values():
    """Generate one cycle of CNC telemetry, phase-aware in demo mode."""
    global _tick, _part_count, _fault_cooldown

    _tick += 1
    phase, progress = _current_phase()

    # ── NORMAL ────────────────────────────────────────────────────────────────
    if phase == "NORMAL":
        motor_speed  = 1500 + 200 * math.sin(_tick / 20) + random.uniform(-20, 20)
        spindle_load = 40 + (motor_speed - 1500) / 30 + random.uniform(-5, 5)
        tool_temp    = 45 + spindle_load * 0.3 + random.uniform(-1, 1)
        feed_rate    = random.choice([600, 800, 1000, 1200]) + random.uniform(-10, 10)
        oee          = random.uniform(88, 93)

        if _fault_cooldown > 0:
            fault_code    = 1
            _fault_cooldown -= 1
        elif random.random() < 0.03:           # 3% random fault
            fault_code    = random.choice([101, 102, 201])
            _fault_cooldown = 3
        else:
            fault_code = 0

    # ── DEGRADING — tool overheating, performance dropping ────────────────────
    elif phase == "DEGRADING":
        motor_speed  = _lerp(1480, 1180, progress) + random.uniform(-15, 15)
        spindle_load = _lerp(52, 82, progress) + random.uniform(-4, 4)
        tool_temp    = _lerp(58, 91, progress) + random.uniform(-1, 2)   # rising
        feed_rate    = _lerp(900, 620, progress) + random.uniform(-10, 10)
        oee          = _lerp(84, 61, progress) + random.uniform(-2, 2)

        # Overtemp faults become increasingly likely
        fault_prob   = _lerp(0.05, 0.40, progress)
        if _fault_cooldown > 0:
            fault_code    = 101
            _fault_cooldown -= 1
        elif random.random() < fault_prob:
            fault_code    = 101   # overtemp warning
            _fault_cooldown = 4
        else:
            fault_code = 0

    # ── FAULT — machine stopped, overtemp alarm active ────────────────────────
    elif phase == "FAULT":
        motor_speed  = max(0.0, _lerp(120, 0, progress))   # coasting to stop
        spindle_load = max(0.0, _lerp(20, 0, progress))
        tool_temp    = _lerp(95, 88, progress) + random.uniform(-0.5, 0.5)  # cooling slowly
        feed_rate    = 0.0
        fault_code   = 101        # overtemp alarm latched
        oee          = random.uniform(0, 8)

    # ── RECOVERING — restart sequence ─────────────────────────────────────────
    else:  # RECOVERING
        motor_speed  = _lerp(300, 1420, progress) + random.uniform(-25, 25)
        spindle_load = _lerp(8, 48, progress) + random.uniform(-3, 3)
        tool_temp    = _lerp(86, 54, progress) + random.uniform(-1, 1)   # cooling
        feed_rate    = _lerp(200, 950, progress) + random.uniform(-10, 10)
        oee          = _lerp(28, 82, progress) + random.uniform(-3, 3)
        fault_code   = 0 if progress > 0.25 else 101   # alarm clears after 25%

    # ── Shared ────────────────────────────────────────────────────────────────
    if _tick % 10 == 0 and motor_speed > 500:
        _part_count += 1

    running = motor_speed > 100

    return {
        "MotorSpeed_RPM":   round(motor_speed, 1),
        "SpindleLoad_Pct":  round(max(0.0, min(100.0, spindle_load)), 1),
        "FeedRate_mm_min":  round(max(0.0, feed_rate), 0),
        "ToolTemperature_C": round(tool_temp, 1),
        "PartCount":        _part_count,
        "FaultCode":        fault_code,
        "RunningStatus":    running,
        "OEE_Pct":          round(max(0.0, min(100.0, oee)), 1),
        "DemoPhase":        phase,   # visible in KQL for troubleshooting
    }


def build_ie_payload() -> str:
    """
    IE S7 Connector Databus format.
    The 'vals' array matches what the IE S7 Connector publishes on topic ie/cnc.
    """
    ts     = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    values = _next_values()

    return json.dumps({
        "timestamp": ts,
        "source":    "ie/cnc",
        "device":    MACHINE_ID,
        "vals": [
            {"id": tag, "val": val, "ts": ts, "qc": 3}
            for tag, val in values.items()
        ],
        # Flat fields alongside vals — useful for Fabric schema auto-detection
        **values,
    })


def main():
    mode_label = (
        f"DEMO (cycle={int(DEMO_CYCLE_SECONDS/60)}min: "
        "Normal→Degrading→Fault→Recovering)"
        if DEMO_MODE else "NORMAL"
    )
    print(f"IE CNC Simulator — machine: {MACHINE_ID}  |  mode: {mode_label}")
    print(f"Target Event Hub: {EVENTHUB_NAME}")
    print(f"Interval: {PUBLISH_INTERVAL}s   |   Ctrl+C to stop\n")

    producer = EventHubProducerClient.from_connection_string(
        conn_str=CONNECTION_STRING,
        eventhub_name=EVENTHUB_NAME,
    )

    try:
        while True:
            payload = build_ie_payload()
            batch   = producer.create_batch()
            event   = EventData(payload)
            event.properties = {
                "content-type": "application/json",
                "source":       "ie/cnc",
                "machine-id":   MACHINE_ID,
            }
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
