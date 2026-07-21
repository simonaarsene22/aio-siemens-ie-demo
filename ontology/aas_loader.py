"""
Shared helper for reading the Siemens AAS (Asset Administration Shell)
submodel. Used by generate_wot_td.py — nothing downstream of the AAS reads
this file directly anymore; see docs/ontology.md for why.
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
AAS_PATH = os.path.join(_HERE, "aas_cnc_submodel.json")
SUBMODEL_ID_SHORT = "CncOperationalData"


def load_operational_data_properties(aas_path: str = AAS_PATH) -> list[dict]:
    """Return the list of Property elements from the CncOperationalData submodel."""
    with open(aas_path, "r", encoding="utf-8") as f:
        env = json.load(f)

    for submodel in env["submodels"]:
        if submodel["idShort"] == SUBMODEL_ID_SHORT:
            return [
                el for el in submodel["submodelElements"]
                if el["modelType"] == "Property"
            ]
    raise KeyError(f"Submodel {SUBMODEL_ID_SHORT!r} not found in {aas_path}")
