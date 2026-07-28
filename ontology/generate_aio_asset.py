"""
Maps a device's WoT Thing Description onto an Azure IoT Operations Asset
custom resource.

Input:  ontology/<device>.td.json     (from generate_wot_td.py)
Output: k8s/asset-<device>.yaml

This deliberately does NOT read a device's AAS submodel directly -- AIO's
connector framework (Akri) resolves assets against a device's WoT Thing
Description, not against a vendor-specific ontology. The AAS -> WoT step
(generate_wot_td.py) is what makes that possible, for every device the same
way, however messy its raw tags are.

Each WoT property affordance becomes one AIO dataPoint. dataSource is the
JSON path carried on the TD's form -- the MQTT/JSON equivalent of an OPC UA
nodeId for a connector that isn't OPC UA-based. Where a device's raw
representation doesn't match the profile (a scaled integer, Fahrenheit, a
0/1 flag), the source form also carries which transform reconciles it --
that logic is noted here as a comment; in a real deployment it's what the
Dataflow between the broker and Fabric would actually apply.

This is illustrative: AIO's native Asset/AssetEndpointProfile CRDs
(deviceregistry.microsoft.com) target OPC UA, media, and REST connectors
most directly today. A raw-MQTT source like these simulators would normally
be onboarded through a Dataflow with a JSON-path transform rather than a
first-class Asset dataPoint -- the shape below shows what the equivalent
semantic mapping looks like either way, keyed off the same WoT TD.

Usage:
    python ontology/generate_wot_td.py grind077     # regenerate the TD first
    python ontology/generate_aio_asset.py grind077
"""
import os
import sys

import devices
import generate_wot_td as wot

_WOT_TYPE_TO_AIO = {
    "number":  "Double",
    "integer": "Int32",
    "boolean": "Boolean",
    "string":  "String",
}


def build_datapoint(prop: dict) -> dict:
    aio_type = _WOT_TYPE_TO_AIO.get(prop["type"])
    if aio_type is None:
        raise ValueError(f"No AIO type mapping for WoT type {prop['type']!r}")
    return {
        "name":       prop["name"],
        "dataSource": prop["jsonPath"],
        "dataType":   aio_type,
        "unit":       prop.get("unit"),
        "transform":  prop.get("transform", "identity"),
    }


def render_yaml(device: dict, datapoints: list[dict]) -> str:
    lines = [
        "# ============================================================",
        f"# Generated from ontology/{os.path.basename(device['td_path'])} by generate_aio_asset.py",
        "# (that file is itself generated from this device's AAS submodel --",
        "#  see docs/ontology.md for the full AAS -> WoT -> AIO pipeline)",
        "# Do not edit by hand -- regenerate instead.",
        "# ============================================================",
        "apiVersion: deviceregistry.microsoft.com/v1",
        "kind: Asset",
        "metadata:",
        f"  name: {device['asset_name']}",
        "  namespace: azure-iot-operations",
        "spec:",
        f"  displayName: {device['display_name']}",
        f"  assetEndpointProfileRef: {device['asset_name']}-mqtt-endpoint",
        f"  externalAssetId: {device['external_asset_id']}",
        "  dataPoints:",
    ]
    for dp in datapoints:
        lines.append(f"    - name: {dp['name']}")
        lines.append(f"      dataSource: \"{dp['dataSource']}\"")
        lines.append(f"      dataType: {dp['dataType']}")
        if dp["unit"]:
            lines.append(f"      unit: \"{dp['unit']}\"")
        if dp["transform"] != "identity":
            lines.append(f"      # raw representation differs from the profile; Dataflow applies transform: {dp['transform']}")
    return "\n".join(lines) + "\n"


def main():
    device_key = sys.argv[1] if len(sys.argv) > 1 else "cnc001"
    device = devices.DEVICES[device_key]

    props = wot.load_td_properties(device["td_path"])
    datapoints = [build_datapoint(p) for p in props]
    yaml_text = render_yaml(device, datapoints)

    with open(device["asset_path"], "w", encoding="utf-8") as f:
        f.write(yaml_text)

    print(f"[{device_key}] Wrote {len(datapoints)} dataPoints -> {os.path.normpath(device['asset_path'])}")


if __name__ == "__main__":
    main()
