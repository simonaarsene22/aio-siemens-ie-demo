"""
Live proof for the demo: resolves every AIO dataPoint's dataSource against a
real device payload, applying whatever transform reconciles that device's
raw representation with the shared profile -- so you can see exactly what
value each ontology property maps to right now, for any device that
implements the profile, however messy its raw tags are.

Run it for the well-behaved device and the hard one, back to back:

    python ontology/show_live_mapping.py             # cnc001 (default)
    python ontology/show_live_mapping.py grind077
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "simulator"))

os.environ.setdefault("EH_CONNECTION_STRING", "Endpoint=sb://demo/;SharedAccessKeyName=x;SharedAccessKey=y")

import devices                    # noqa: E402
import generate_wot_td as wot     # noqa: E402
import generate_aio_asset as gen  # noqa: E402
import transforms                 # noqa: E402

_PAYLOAD_BUILDERS = {
    "cnc001":   ("simulate_ie_cnc", "build_ie_payload"),
    "grind077": ("simulate_grind077_plc", "build_raw_payload"),
}


def _sample_raw_payload(device_key: str) -> dict:
    module_name, fn_name = _PAYLOAD_BUILDERS[device_key]
    module = __import__(module_name)
    return json.loads(getattr(module, fn_name)())


def _fmt_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{round(value, 2)}"
    return str(value)


def main():
    device_key = sys.argv[1] if len(sys.argv) > 1 else "cnc001"
    device = devices.DEVICES[device_key]

    raw = _sample_raw_payload(device_key)
    props = wot.load_td_properties(device["td_path"])

    rows = []
    for prop in props:
        dp = gen.build_datapoint(prop)
        raw_value = raw.get(prop["rawField"])
        resolved = None if raw_value is None else transforms.apply(prop["transform"], raw_value)
        rows.append((
            dp["name"],
            prop["rawField"],
            _fmt_value(raw_value),
            prop["transform"],
            _fmt_value(resolved),
            dp["unit"] or "",
        ))

    headers = ("AIO dataPoint", "raw field", "raw value", "transform", "resolved value", "unit")
    widths = [max(len(str(r[i])) for r in ([headers] + rows)) for i in range(len(headers))]

    def fmt(row):
        return "  ".join(str(c).ljust(w) for c, w in zip(row, widths))

    print(f"Device: {device['display_name']}  ({device_key})")
    print(f"Profile: {os.path.basename(device['aas_path'])} -> {os.path.basename(device['td_path'])}\n")
    print(fmt(headers))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(fmt(row))

    print(f"\nSample from device={raw['device']!r} at {raw['timestamp']}")


if __name__ == "__main__":
    main()
