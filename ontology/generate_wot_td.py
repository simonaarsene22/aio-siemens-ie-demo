"""
Maps the Siemens AAS (Asset Administration Shell) submodel for the CNC asset
onto a W3C Web of Things (WoT) Thing Description.

Input:  ontology/aas_cnc_submodel.json   (Siemens-side ontology)
Output: ontology/cnc-001.td.json         (WoT capability model AIO reads)

This is the middle layer AIO actually relies on: Azure IoT Operations'
connector framework (Akri) describes what a device/asset exposes using a WoT
Thing Description, and the Asset resource (see generate_aio_asset.py) then
selects which of those properties to ingest and where to send them. Putting
WoT in between means the Siemens ontology and the AIO asset never talk
directly to each other — they agree through a shared, protocol-neutral
capability model.

The link is provable, not asserted: each WoT property's "@type" carries the
*exact same* semanticId URN as the corresponding AAS Property, via the
"siemens" JSON-LD context prefix below.

Usage:
    python ontology/generate_wot_td.py
"""
import json
import os

import aas_loader

_AAS_TYPE_TO_WOT = {
    "xs:double":  "number",
    "xs:int":     "integer",
    "xs:boolean": "boolean",
    "xs:string":  "string",
}

_HERE = os.path.dirname(os.path.abspath(__file__))
TD_PATH = os.path.join(_HERE, "cnc-001.td.json")

SEMANTIC_PREFIX = "urn:siemens:ie:cnc:property:"
THING_ID = "urn:siemens:ie:asset:CNC-001"
MQTT_TOPIC = "ie/cnc"


def _semantic_suffix(prop: dict) -> str:
    """The bare property name from the AAS semanticId, e.g. MotorSpeed_RPM."""
    semantic_id = prop["semanticId"]["keys"][0]["value"]
    if not semantic_id.startswith(SEMANTIC_PREFIX):
        raise ValueError(f"{prop['idShort']}: semanticId {semantic_id!r} has no recognized prefix")
    return semantic_id[len(SEMANTIC_PREFIX):]


def build_property_affordance(prop: dict) -> dict:
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
                "href": f"mqtt://<AIO_BROKER_HOST>:1883/{MQTT_TOPIC}",
                "op": "observeproperty",
                "contentType": "application/json",
                # Not (yet) a standard WoT MQTT binding keyword — the pragmatic
                # extension used here to say "this property's value lives at
                # this JSON path inside the topic's combined payload", since
                # the IE Databus publishes one JSON object per topic rather
                # than one topic per tag.
                "siemens:jsonPath": f"$.{prop['idShort']}",
            }
        ],
    }
    if prop.get("unit"):
        affordance["unit"] = prop["unit"]
    if prop.get("description"):
        affordance["description"] = prop["description"][0]["text"]
    return affordance


def build_thing_description(props: list[dict]) -> dict:
    return {
        "@context": [
            "https://www.w3.org/2022/wot/td/v1.1",
            {"siemens": SEMANTIC_PREFIX},
        ],
        "id": THING_ID,
        "title": "SINUMERIK CNC-001",
        "description": "WoT capability model for the Siemens IE CNC asset, generated from its AAS submodel.",
        "securityDefinitions": {"nosec_sc": {"scheme": "nosec"}},
        "security": ["nosec_sc"],
        "properties": {
            prop["idShort"]: build_property_affordance(prop)
            for prop in props
        },
    }


def load_td_properties(td_path: str = TD_PATH) -> list[dict]:
    """Flatten the TD's properties map back into a list AIO-side tooling can consume."""
    with open(td_path, "r", encoding="utf-8") as f:
        td = json.load(f)

    result = []
    for name, affordance in td["properties"].items():
        form = affordance["forms"][0]
        result.append({
            "name":      name,
            "type":      affordance["type"],
            "unit":      affordance.get("unit"),
            "jsonPath":  form["siemens:jsonPath"],
            "semanticType": affordance["@type"],
        })
    return result


def main():
    props = aas_loader.load_operational_data_properties()
    td = build_thing_description(props)

    with open(TD_PATH, "w", encoding="utf-8") as f:
        json.dump(td, f, indent=2)
        f.write("\n")

    print(f"Wrote {len(props)} WoT properties -> {os.path.normpath(TD_PATH)}")


if __name__ == "__main__":
    main()
