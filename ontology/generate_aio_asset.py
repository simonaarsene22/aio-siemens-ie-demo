"""
Maps the WoT Thing Description for the CNC asset onto an Azure IoT
Operations Asset custom resource.

Input:  ontology/cnc-001.td.json   (WoT capability model, from generate_wot_td.py)
Output: k8s/asset-cnc-001.yaml     (AIO-side asset definition)

This deliberately does NOT read the Siemens AAS submodel directly — AIO's
connector framework (Akri) resolves assets against a device's WoT Thing
Description, not against a vendor-specific ontology. The AAS -> WoT step
(generate_wot_td.py) is what makes that possible.

Each WoT property affordance becomes one AIO dataPoint. dataSource is the
JSON path carried on the TD's form (see generate_wot_td.py) — the MQTT/JSON
equivalent of an OPC UA nodeId for a connector that isn't OPC UA-based.

This is illustrative: AIO's native Asset/AssetEndpointProfile CRDs
(deviceregistry.microsoft.com) target OPC UA, media, and REST connectors
most directly today. A raw-MQTT source like this one is normally onboarded
through a Dataflow with a JSON-path transform rather than a first-class
Asset dataPoint — the shape below shows what the equivalent semantic mapping
looks like either way, keyed off the same WoT TD.

Usage:
    python ontology/generate_wot_td.py     # regenerate the TD first
    python ontology/generate_aio_asset.py
"""
import os

import generate_wot_td as wot

_WOT_TYPE_TO_AIO = {
    "number":  "Double",
    "integer": "Int32",
    "boolean": "Boolean",
    "string":  "String",
}

_HERE = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(_HERE, "..", "k8s", "asset-cnc-001.yaml")


def build_datapoint(prop: dict) -> dict:
    aio_type = _WOT_TYPE_TO_AIO.get(prop["type"])
    if aio_type is None:
        raise ValueError(f"No AIO type mapping for WoT type {prop['type']!r}")
    return {
        "name":       prop["name"],
        "dataSource": prop["jsonPath"],
        "dataType":   aio_type,
        "unit":       prop.get("unit"),
    }


def render_yaml(datapoints: list[dict]) -> str:
    lines = [
        "# ============================================================",
        "# Generated from ontology/cnc-001.td.json by generate_aio_asset.py",
        "# (that file is itself generated from aas_cnc_submodel.json —",
        "#  see docs/ontology.md for the full AAS -> WoT -> AIO pipeline)",
        "# Do not edit by hand — regenerate instead.",
        "#",
        "# Illustrative AIO Asset definition: maps each WoT property",
        "# affordance onto one dataPoint sourced from the ie/cnc MQTT topic",
        "# (see simulator/simulate_ie_cnc.py).",
        "# ============================================================",
        "apiVersion: deviceregistry.microsoft.com/v1",
        "kind: Asset",
        "metadata:",
        "  name: cnc-001",
        "  namespace: azure-iot-operations",
        "spec:",
        "  displayName: SINUMERIK CNC-001",
        "  assetEndpointProfileRef: cnc-mqtt-endpoint",
        "  externalAssetId: urn:siemens:ie:asset:CNC-001",
        "  dataPoints:",
    ]
    for dp in datapoints:
        lines.append(f"    - name: {dp['name']}")
        lines.append(f"      dataSource: \"{dp['dataSource']}\"")
        lines.append(f"      dataType: {dp['dataType']}")
        if dp["unit"]:
            lines.append(f"      unit: \"{dp['unit']}\"")
    return "\n".join(lines) + "\n"


def main():
    props = wot.load_td_properties()
    datapoints = [build_datapoint(p) for p in props]
    yaml_text = render_yaml(datapoints)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(yaml_text)

    print(f"Wrote {len(datapoints)} dataPoints -> {os.path.normpath(OUT_PATH)}")


if __name__ == "__main__":
    main()
