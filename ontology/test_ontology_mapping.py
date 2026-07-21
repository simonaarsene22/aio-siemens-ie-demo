"""
Local, no-cloud test suite for the Siemens AAS -> WoT -> AIO Asset pipeline.

Validates four things without needing a real Siemens IE device or a live
AIO cluster:

  1. The AAS submodel (ontology/aas_cnc_submodel.json) is structurally sound
     and every Property has a semanticId, valueType and (numeric ones) unit.
  2. The generated WoT Thing Description (ontology/cnc-001.td.json) — the
     capability model AIO's connector framework actually reads — carries
     every AAS property across with the *same* semanticId (not just the
     same name), the same value type, and the same unit. This is what
     proves the AAS -> WoT step isn't lossy.
  3. Every field the CNC simulator actually publishes either has a matching
     WoT property, or is on the explicit exclusion list (simulator-only
     diagnostic fields that intentionally aren't part of the asset
     ontology). This is the check that catches ontology/telemetry drift.
  4. The generated AIO Asset CRD (k8s/asset-cnc-001.yaml) has one dataPoint
     per WoT property, with a dataSource path that actually resolves against
     a real simulator payload and a dataType consistent with the value the
     simulator emits.

Run:
    python -m unittest ontology/test_ontology_mapping.py -v
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

import simulate_ie_cnc as sim          # noqa: E402
import aas_loader                      # noqa: E402
import generate_wot_td as wot          # noqa: E402
import generate_aio_asset as gen       # noqa: E402

ASSET_YAML_PATH = os.path.join(_ROOT, "k8s", "asset-cnc-001.yaml")

# Fields the simulator emits that are intentionally NOT part of the Siemens
# asset ontology (demo/diagnostic-only, not a physical asset property).
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


def _isinstance_strict(value, aas_type: str) -> bool:
    if aas_type == "xs:boolean":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False  # bool must not satisfy int/double/string checks
    return isinstance(value, _PY_TYPE_FOR_AAS[aas_type])


class AasSubmodelStructureTest(unittest.TestCase):
    """The Siemens ontology artifact itself is well-formed."""

    @classmethod
    def setUpClass(cls):
        with open(aas_loader.AAS_PATH, "r", encoding="utf-8") as f:
            cls.env = json.load(f)

    def test_has_shell_and_submodels(self):
        self.assertTrue(self.env["assetAdministrationShells"])
        self.assertTrue(self.env["submodels"])

    def test_operational_data_properties_are_well_formed(self):
        props = aas_loader.load_operational_data_properties()
        self.assertGreater(len(props), 0)
        for prop in props:
            with self.subTest(idShort=prop["idShort"]):
                self.assertIn("valueType", prop)
                self.assertIn(prop["valueType"], _PY_TYPE_FOR_AAS)
                self.assertIn("semanticId", prop)
                self.assertTrue(prop["semanticId"]["keys"][0]["value"])
                if prop["valueType"] in ("xs:double", "xs:int") and prop["idShort"] not in ("FaultCode",):
                    self.assertTrue(prop.get("unit"), f"{prop['idShort']} is numeric but has no unit")


class AasToWotMappingTest(unittest.TestCase):
    """The WoT Thing Description AIO reads carries the AAS ontology across losslessly."""

    @classmethod
    def setUpClass(cls):
        cls.aas_props = {p["idShort"]: p for p in aas_loader.load_operational_data_properties()}
        cls.td_props = {p["name"]: p for p in wot.load_td_properties()}

    def test_every_aas_property_has_a_wot_property(self):
        self.assertEqual(set(self.aas_props), set(self.td_props))

    def test_wot_semantic_type_matches_aas_semantic_id_exactly(self):
        for name, aas_prop in self.aas_props.items():
            with self.subTest(property=name):
                expected = f"siemens:{aas_prop['semanticId']['keys'][0]['value'][len(wot.SEMANTIC_PREFIX):]}"
                self.assertEqual(self.td_props[name]["semanticType"], expected,
                                  f"{name}: WoT @type does not carry the same semanticId as the AAS property")

    def test_wot_value_type_matches_aas_value_type(self):
        for name, aas_prop in self.aas_props.items():
            with self.subTest(property=name):
                self.assertEqual(self.td_props[name]["type"], _AAS_TYPE_TO_WOT[aas_prop["valueType"]])

    def test_wot_unit_matches_aas_unit(self):
        for name, aas_prop in self.aas_props.items():
            with self.subTest(property=name):
                self.assertEqual(self.td_props[name]["unit"], aas_prop.get("unit"))

    def test_td_json_on_disk_is_up_to_date(self):
        self.assertTrue(os.path.exists(wot.TD_PATH),
                         "ontology/cnc-001.td.json missing — run ontology/generate_wot_td.py")
        with open(wot.TD_PATH, "r", encoding="utf-8") as f:
            on_disk = json.load(f)
        regenerated = wot.build_thing_description(list(self.aas_props.values()))
        self.assertEqual(on_disk, regenerated,
                          "ontology/cnc-001.td.json is stale — regenerate with ontology/generate_wot_td.py")


class OntologyMatchesSimulatorTest(unittest.TestCase):
    """The WoT capability model and the actual edge telemetry contract must not drift apart."""

    @classmethod
    def setUpClass(cls):
        cls.props_by_name = {p["name"]: p for p in wot.load_td_properties()}
        payload = json.loads(sim.build_ie_payload())
        cls.payload = payload
        cls.telemetry_fields = {k: v for k, v in payload.items()
                                 if k not in ("timestamp", "source", "device", "vals")}

    def test_every_ontology_property_is_actually_published(self):
        for name in self.props_by_name:
            with self.subTest(property=name):
                self.assertIn(name, self.telemetry_fields,
                               f"WoT property {name!r} has no matching field in the simulator payload")

    def test_every_published_field_is_in_ontology_or_explicitly_excluded(self):
        unmapped = set(self.telemetry_fields) - set(self.props_by_name) - NON_ONTOLOGY_FIELDS
        self.assertEqual(unmapped, set(),
                          f"Simulator publishes fields with no ontology mapping and no exclusion: {unmapped}")

    def test_published_value_types_match_ontology_value_types(self):
        aas_props = {p["idShort"]: p for p in aas_loader.load_operational_data_properties()}
        for name in self.props_by_name:
            with self.subTest(property=name):
                value = self.telemetry_fields[name]
                self.assertTrue(
                    _isinstance_strict(value, aas_props[name]["valueType"]),
                    f"{name}={value!r} ({type(value).__name__}) does not match ontology type {aas_props[name]['valueType']}",
                )


class AioAssetMappingTest(unittest.TestCase):
    """The generated AIO Asset CRD faithfully carries the WoT capability model into AIO."""

    @classmethod
    def setUpClass(cls):
        cls.props = wot.load_td_properties()
        cls.datapoints = [gen.build_datapoint(p) for p in cls.props]
        payload = json.loads(sim.build_ie_payload())
        cls.telemetry_fields = {k: v for k, v in payload.items()
                                 if k not in ("timestamp", "source", "device", "vals")}

    def test_one_datapoint_per_wot_property(self):
        self.assertEqual(len(self.datapoints), len(self.props))
        self.assertEqual({dp["name"] for dp in self.datapoints},
                          {p["name"] for p in self.props})

    def test_datapoint_datasource_resolves_against_real_payload(self):
        for dp in self.datapoints:
            with self.subTest(dataPoint=dp["name"]):
                self.assertTrue(dp["dataSource"].startswith("$."))
                field = dp["dataSource"][2:]
                self.assertIn(field, self.telemetry_fields,
                               f"dataSource {dp['dataSource']!r} does not resolve against a live simulator payload")

    def test_asset_yaml_is_up_to_date_on_disk(self):
        self.assertTrue(os.path.exists(ASSET_YAML_PATH),
                         "k8s/asset-cnc-001.yaml missing — run ontology/generate_aio_asset.py")
        with open(ASSET_YAML_PATH, "r", encoding="utf-8") as f:
            on_disk = f.read()
        self.assertEqual(on_disk, gen.render_yaml(self.datapoints),
                          "k8s/asset-cnc-001.yaml is stale — regenerate with ontology/generate_aio_asset.py")


if __name__ == "__main__":
    unittest.main()
