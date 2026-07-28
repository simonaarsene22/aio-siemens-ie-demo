"""
Registry of devices that implement the shared machine-operational-data
profile. Adding a device to this demo means adding one entry here (plus its
AAS file, and a binding file only if its raw tags don't already match the
profile 1:1) -- nothing else in the pipeline is device-specific.
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))

DEVICES = {
    "cnc001": {
        "aas_path": os.path.join(_HERE, "aas_cnc_submodel.json"),
        "binding_path": None,  # raw simulator fields already match the profile 1:1
        "td_path": os.path.join(_HERE, "cnc-001.td.json"),
        "asset_path": os.path.join(_HERE, "..", "k8s", "asset-cnc-001.yaml"),
        "asset_name": "cnc-001",
        "display_name": "SINUMERIK CNC-001",
        "external_asset_id": "urn:siemens:ie:asset:CNC-001",
        "mqtt_topic": "ie/cnc",
    },
    "grind077": {
        "aas_path": os.path.join(_HERE, "aas_grind077_submodel.json"),
        "binding_path": os.path.join(_HERE, "bindings", "grind077_binding.json"),
        "td_path": os.path.join(_HERE, "grind-077.td.json"),
        "asset_path": os.path.join(_HERE, "..", "k8s", "asset-grind-077.yaml"),
        "asset_name": "grind-077",
        "display_name": "Legacy S7-300 Grinding Cell GRIND-077",
        "external_asset_id": "urn:siemens:ie:asset:GRIND-077",
        "mqtt_topic": "s7/grind077",
    },
}


def resolve_binding(device_key: str, properties: list[dict]) -> dict:
    """
    Return {idShort: {"rawField": ..., "transform": ...}} for a device.
    If it has no binding_path, every property defaults to an identity
    mapping (rawField == idShort, transform == "identity") -- this is
    CNC-001's case: no reconciliation needed because the simulator already
    speaks the profile's language.
    """
    binding_path = DEVICES[device_key]["binding_path"]
    if binding_path is None:
        return {p["idShort"]: {"rawField": p["idShort"], "transform": "identity"} for p in properties}

    with open(binding_path, "r", encoding="utf-8") as f:
        binding = json.load(f)
    return {m["idShort"]: {"rawField": m["rawField"], "transform": m["transform"]} for m in binding["mappings"]}
