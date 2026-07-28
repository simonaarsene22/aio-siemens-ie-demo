"""
Local, no-cloud test suite for the Siemens AAS -> WoT -> AIO Asset pipeline,
run across two devices on purpose: CNC-001 (an IE-connected machine whose
raw tags already match the shared profile) and GRIND-077 (a legacy S7-300
PLC whose raw tags are genuinely messy -- cryptic addresses, a scaled
integer, Fahrenheit, a 0/1 flag, a 0..1 fraction). Both are supposed to
resolve into the identical canonical shape; these tests are what prove that,
rather than asserting it.

Validates, for every device in ontology/devices.py:

  1. Its AAS submodel is structurally sound.
  2. It genuinely conforms to the shared profile (ontology/profiles/) --
     same submodel-level semanticId, same canonical property set, same
     type/unit/semanticId per property as every other conforming device.
  3. Its raw simulator payload is exactly as messy (or as clean) as claimed
     -- a sanity check on the premise, not just the pipeline.
  4. Its WoT Thing Description carries the AAS ontology across losslessly.
  5. Applying its binding's transform to a real raw payload resolves every
     property to a value matching the ontology's declared type.
  6. Its generated AIO Asset CRD has one dataPoint per WoT property, with a
     dataSource that resolves against a live raw payload.

Run:
    python -m unittest ontology.test_ontology_mapping -v
"""
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, os.path.join(_ROOT, "simulator"))
sys.path.insert(0, _HERE)

os.environ.setdefault("EH_CONNECTION_STRING", "Endpoint=sb://unit-test/;SharedAccessKeyName=x;SharedAccessKey=y")

import simulate_ie_cnc as sim_cnc            # noqa: E402
import simulate_grind077_plc as sim_grind    # noqa: E402
import aas_loader                            # noqa: E402
import devices                               # noqa: E402
import transforms                            # noqa: E402
import generate_wot_td as wot                # noqa: E402
import generate_aio_asset as gen             # noqa: E402

# Fields CNC-001's simulator emits that are intentionally NOT part of the
# profile (demo/diagnostic-only, not a physical asset property).
NON_ONTOLOGY_FIELDS = {"DemoPhase"}

_AAS_TYPE_TO_WOT = {
    "xs:double":  "number",
    "xs:int":     "integer",
    "xs:boolean": "boolean",
    "xs:string":  "string",
}

_PY_TYPE_FOR_AAS = {
    "xs:double":  (int, float),   # bool is a subclass of int in Python -> excluded explicitly below
    "xs:int":     (int,),
    "xs:boolean": (bool,),
    "xs:string":  (str,),
}

_RAW_PAYLOAD_BUILDERS = {
    "cnc001":   lambda: json.loads(sim_cnc.build_ie_payload()),
    "grind077": lambda: json.loads(sim_grind.build_raw_payload()),
}


def _isinstance_strict(value, aas_type: str) -> bool:
    if aas_type == "xs:boolean":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False  # bool must not satisfy int/double/string checks
    return isinstance(value, _PY_TYPE_FOR_AAS[aas_type])


def _canonical_properties(device_key: str) -> dict:
    device = devices.DEVICES[device_key]
    return {p["idShort"]: p for p in aas_loader.load_operational_data_properties(device["aas_path"])}


class AasSubmodelStructureTest(unittest.TestCase):
    """Every device's AAS ontology artifact is well-formed."""

    def test_operational_data_properties_are_well_formed(self):
        for key, device in devices.DEVICES.items():
            props = aas_loader.load_operational_data_properties(device["aas_path"])
            with self.subTest(device=key):
                self.assertGreater(len(props), 0)
            for prop in props:
                with self.subTest(device=key, idShort=prop["idShort"]):
                    self.assertIn("valueType", prop)
                    self.assertIn(prop["valueType"], _PY_TYPE_FOR_AAS)
                    self.assertIn("semanticId", prop)
                    self.assertTrue(prop["semanticId"]["keys"][0]["value"])
                    if prop["valueType"] in ("xs:double", "xs:int") and prop["idShort"] != "FaultCode":
                        self.assertTrue(prop.get("unit"), f"{key}.{prop['idShort']} is numeric but has no unit")


class ProfileConformanceTest(unittest.TestCase):
    """
    Both devices genuinely implement the same shared profile -- this is what
    makes them interchangeable to AIO, not a coincidence of naming.
    """

    def test_submodel_level_semantic_id_matches_the_profile_for_every_device(self):
        for key, device in devices.DEVICES.items():
            with self.subTest(device=key):
                with open(device["aas_path"], encoding="utf-8") as f:
                    env = json.load(f)
                matches = [
                    sm for sm in env["submodels"]
                    if sm.get("semanticId", {}).get("keys", [{}])[0].get("value") == aas_loader.PROFILE_ID
                ]
                self.assertEqual(len(matches), 1,
                                  f"{key}: expected exactly one submodel conforming to {aas_loader.PROFILE_ID}")

    def test_both_devices_expose_the_identical_canonical_property_set(self):
        by_device = {key: _canonical_properties(key) for key in devices.DEVICES}
        first, *rest = by_device
        for other in rest:
            with self.subTest(devices=f"{first} vs {other}"):
                self.assertEqual(set(by_device[first]), set(by_device[other]),
                                  "Devices conforming to the same profile must expose the same property names")

    def test_both_devices_agree_on_semantic_id_type_and_unit_per_property(self):
        by_device = {key: _canonical_properties(key) for key in devices.DEVICES}
        first, *rest = by_device
        for name in by_device[first]:
            for other in rest:
                with self.subTest(property=name, device=other):
                    a, b = by_device[first][name], by_device[other][name]
                    self.assertEqual(a["semanticId"]["keys"][0]["value"], b["semanticId"]["keys"][0]["value"])
                    self.assertEqual(a["valueType"], b["valueType"])
                    self.assertEqual(a.get("unit"), b.get("unit"))


class RawPayloadPremiseTest(unittest.TestCase):
    """
    Sanity check on the premise, not the pipeline: GRIND-077's raw payload
    must NOT already use canonical names (otherwise the binding/transform
    layer wouldn't be proving anything), and CNC-001's must.
    """

    def test_grind077_raw_payload_uses_no_canonical_field_names(self):
        raw = _RAW_PAYLOAD_BUILDERS["grind077"]()
        canonical = set(_canonical_properties("grind077"))
        overlap = canonical & set(raw)
        self.assertEqual(overlap, set(),
                          f"GRIND-077's raw payload already uses canonical names {overlap} — "
                          "the binding wouldn't be demonstrating anything")

    def test_cnc001_raw_payload_already_uses_canonical_field_names(self):
        raw = _RAW_PAYLOAD_BUILDERS["cnc001"]()
        canonical = set(_canonical_properties("cnc001"))
        missing = canonical - set(raw)
        self.assertEqual(missing, set(),
                          "CNC-001 is supposed to need no binding — its raw fields should already match the profile")


class AasToWotMappingTest(unittest.TestCase):
    """For every device, the WoT Thing Description AIO reads carries the AAS ontology across losslessly."""

    def test_every_aas_property_has_a_matching_wot_property(self):
        for key, device in devices.DEVICES.items():
            aas_props = _canonical_properties(key)
            td_props = {p["name"]: p for p in wot.load_td_properties(device["td_path"])}
            with self.subTest(device=key):
                self.assertEqual(set(aas_props), set(td_props))
            for name, aas_prop in aas_props.items():
                with self.subTest(device=key, property=name):
                    expected_type = f"siemens:{aas_prop['semanticId']['keys'][0]['value'][len(wot.SEMANTIC_PREFIX):]}"
                    self.assertEqual(td_props[name]["semanticType"], expected_type)
                    self.assertEqual(td_props[name]["type"], _AAS_TYPE_TO_WOT[aas_prop["valueType"]])
                    self.assertEqual(td_props[name]["unit"], aas_prop.get("unit"))

    def test_td_json_on_disk_is_up_to_date(self):
        for key, device in devices.DEVICES.items():
            with self.subTest(device=key):
                self.assertTrue(os.path.exists(device["td_path"]),
                                 f"{device['td_path']} missing — run ontology/generate_wot_td.py {key}")
                with open(device["td_path"], encoding="utf-8") as f:
                    on_disk = json.load(f)
                regenerated = wot.build_thing_description(key)
                self.assertEqual(on_disk, regenerated,
                                  f"{device['td_path']} is stale — regenerate with ontology/generate_wot_td.py {key}")


class BindingResolvesLiveTelemetryTest(unittest.TestCase):
    """
    The hard-problem proof: applying each device's binding + transform to a
    real raw payload must resolve every canonical property to a value
    matching the ontology's declared type -- for the messy device just as
    much as the clean one.
    """

    def test_every_wot_property_rawfield_is_present_in_a_live_payload(self):
        for key, device in devices.DEVICES.items():
            raw = _RAW_PAYLOAD_BUILDERS[key]()
            for prop in wot.load_td_properties(device["td_path"]):
                with self.subTest(device=key, property=prop["name"]):
                    self.assertIn(prop["rawField"], raw,
                                  f"{key}.{prop['name']}: rawField {prop['rawField']!r} not present in a live payload")

    def test_resolved_values_match_ontology_type_after_transform(self):
        for key, device in devices.DEVICES.items():
            raw = _RAW_PAYLOAD_BUILDERS[key]()
            aas_props = _canonical_properties(key)
            for prop in wot.load_td_properties(device["td_path"]):
                with self.subTest(device=key, property=prop["name"]):
                    resolved = transforms.apply(prop["transform"], raw[prop["rawField"]])
                    expected_type = aas_props[prop["name"]]["valueType"]
                    self.assertTrue(
                        _isinstance_strict(resolved, expected_type),
                        f"{key}.{prop['name']}: resolved {resolved!r} ({type(resolved).__name__}) does not "
                        f"match ontology type {expected_type} after transform {prop['transform']!r}",
                    )

    def test_cnc001_diagnostic_field_is_explicitly_excluded_not_dropped(self):
        raw = _RAW_PAYLOAD_BUILDERS["cnc001"]()
        telemetry_fields = {k for k in raw if k not in ("timestamp", "source", "device", "vals")}
        canonical = set(_canonical_properties("cnc001"))
        unmapped = telemetry_fields - canonical
        self.assertEqual(unmapped, NON_ONTOLOGY_FIELDS,
                          f"CNC-001 publishes unexpected unmapped fields: {unmapped - NON_ONTOLOGY_FIELDS}")


class AioAssetMappingTest(unittest.TestCase):
    """The generated AIO Asset CRD faithfully carries each device's WoT capability model into AIO."""

    def test_one_datapoint_per_wot_property(self):
        for key, device in devices.DEVICES.items():
            props = wot.load_td_properties(device["td_path"])
            datapoints = [gen.build_datapoint(p) for p in props]
            with self.subTest(device=key):
                self.assertEqual(len(datapoints), len(props))
                self.assertEqual({dp["name"] for dp in datapoints}, {p["name"] for p in props})

    def test_datapoint_datasource_resolves_against_a_live_raw_payload(self):
        for key, device in devices.DEVICES.items():
            raw = _RAW_PAYLOAD_BUILDERS[key]()
            for prop in wot.load_td_properties(device["td_path"]):
                dp = gen.build_datapoint(prop)
                with self.subTest(device=key, dataPoint=dp["name"]):
                    field = wot.from_json_path(dp["dataSource"])
                    self.assertIn(field, raw,
                                  f"{key}: dataSource {dp['dataSource']!r} does not resolve against a live raw payload")

    def test_asset_yaml_is_up_to_date_on_disk(self):
        for key, device in devices.DEVICES.items():
            with self.subTest(device=key):
                self.assertTrue(os.path.exists(device["asset_path"]),
                                 f"{device['asset_path']} missing — run ontology/generate_aio_asset.py {key}")
                with open(device["asset_path"], encoding="utf-8") as f:
                    on_disk = f.read()
                props = wot.load_td_properties(device["td_path"])
                datapoints = [gen.build_datapoint(p) for p in props]
                regenerated = gen.render_yaml(device, datapoints)
                self.assertEqual(on_disk, regenerated,
                                  f"{device['asset_path']} is stale — regenerate with ontology/generate_aio_asset.py {key}")


if __name__ == "__main__":
    unittest.main()
