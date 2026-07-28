"""
Maps a device's AAS submodel (conforming to the shared
machine-operational-data profile, see ontology/profiles/) onto a W3C Web of
Things Thing Description.

Input:  the device's AAS file + its binding file, if it has one (ontology/devices.py)
Output: ontology/<device>.td.json

This is the middle layer AIO actually relies on: Azure IoT Operations'
connector framework (Akri) describes what a device/asset exposes using a WoT
Thing Description, and the Asset resource (see generate_aio_asset.py) then
selects which of those properties to ingest and where to send them. Putting
WoT in between means the Siemens ontology and the AIO asset never talk
directly to each other -- they agree through a shared, protocol-neutral
capability model.

The link is provable, not asserted: each WoT property's "@type" carries the
*exact same* semanticId URN as the corresponding AAS Property, via the
"siemens" JSON-LD context prefix below -- for every device, not just the
well-behaved one. For a device whose raw tags don't already match the
profile (see devices without binding_path == None), the form also carries
the raw field it actually reads and the transform that reconciles it --
that's the part that makes this more than a rename.

Usage:
    python ontology/generate_wot_td.py            # cnc001 (default)
    python ontology/generate_wot_td.py grind077
"""
import json
import os
import sys

import aas_loader
import devices

_AAS_TYPE_TO_WOT = {
    "xs:double":  "number",
    "xs:int":     "integer",
    "xs:boolean": "boolean",
    "xs:string":  "string",
}

_HERE = os.path.dirname(os.path.abspath(__file__))

SEMANTIC_PREFIX = "urn:siemens:ie:profile:machine-operational-data:v1:"


def to_json_path(raw_field: str) -> str:
    """$.rawField for plain identifiers; $.['raw.field'] when it isn't one
    (real PLC tag addresses like DB10.DBD4 contain dots that would otherwise
    be read as nested path segments)."""
    if raw_field.isidentifier():
        return f"$.{raw_field}"
    return f"$.['{raw_field}']"


def from_json_path(json_path: str) -> str:
    if json_path.startswith("$.['") and json_path.endswith("']"):
        return json_path[len("$.['"):-len("']")]
    return json_path[len("$."):]


def _semantic_suffix(prop: dict) -> str:
    """The bare property name from the AAS semanticId, e.g. MotorSpeed_RPM."""
    semantic_id = prop["semanticId"]["keys"][0]["value"]
    if not semantic_id.startswith(SEMANTIC_PREFIX):
        raise ValueError(f"{prop['idShort']}: semanticId {semantic_id!r} is not under the shared profile")
    return semantic_id[len(SEMANTIC_PREFIX):]


def build_property_affordance(prop: dict, binding_entry: dict, mqtt_topic: str) -> dict:
    wot_type = _AAS_TYPE_TO_WOT.get(prop["valueType"])
    if wot_type is None:
        raise ValueError(f"No WoT type mapping for AAS valueType {prop['valueType']!r}")

    affordance = {
        "@type": f"siemens:{_semantic_suffix(prop)}",
        "type": wot_type,
        "readOnly": True,
        "observable": True,
        "forms": [
            {
                "href": f"mqtt://<AIO_BROKER_HOST>:1883/{mqtt_topic}",
                "op": "observeproperty",
                "contentType": "application/json",
                "siemens:jsonPath": to_json_path(binding_entry["rawField"]),
                "siemens:transform": binding_entry["transform"],
            }
        ],
    }
    if prop.get("unit"):
        affordance["unit"] = prop["unit"]
    if prop.get("description"):
        affordance["description"] = prop["description"][0]["text"]
    return affordance


def build_thing_description(device_key: str) -> dict:
    device = devices.DEVICES[device_key]
    props = aas_loader.load_operational_data_properties(device["aas_path"])
    binding = devices.resolve_binding(device_key, props)

    return {
        "@context": [
            "https://www.w3.org/2022/wot/td/v1.1",
            {"siemens": aas_loader.PROFILE_ID + ":"},
        ],
        "id": device["external_asset_id"],
        "title": device["display_name"],
        "description": f"WoT capability model for {device['display_name']}, generated from its AAS submodel. Conforms to {aas_loader.PROFILE_ID}.",
        "securityDefinitions": {"nosec_sc": {"scheme": "nosec"}},
        "security": ["nosec_sc"],
        "properties": {
            prop["idShort"]: build_property_affordance(prop, binding[prop["idShort"]], device["mqtt_topic"])
            for prop in props
        },
    }


def load_td_properties(td_path: str) -> list[dict]:
    """Flatten a TD's properties map back into a list AIO-side tooling can consume."""
    with open(td_path, "r", encoding="utf-8") as f:
        td = json.load(f)

    result = []
    for name, affordance in td["properties"].items():
        form = affordance["forms"][0]
        result.append({
            "name":         name,
            "type":         affordance["type"],
            "unit":         affordance.get("unit"),
            "jsonPath":     form["siemens:jsonPath"],
            "rawField":     from_json_path(form["siemens:jsonPath"]),
            "transform":    form["siemens:transform"],
            "semanticType": affordance["@type"],
        })
    return result


def main():
    device_key = sys.argv[1] if len(sys.argv) > 1 else "cnc001"
    device = devices.DEVICES[device_key]
    td = build_thing_description(device_key)

    with open(device["td_path"], "w", encoding="utf-8") as f:
        json.dump(td, f, indent=2)
        f.write("\n")

    print(f"[{device_key}] Wrote {len(td['properties'])} WoT properties -> {os.path.normpath(device['td_path'])}")


if __name__ == "__main__":
    main()
