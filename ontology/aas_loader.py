"""
Shared helper for reading a device's AAS (Asset Administration Shell)
submodel and finding the part of it that conforms to the shared
machine-operational-data profile (ontology/profiles/).
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
AAS_PATH = os.path.join(_HERE, "aas_cnc_submodel.json")
PROFILE_ID = "urn:siemens:ie:profile:machine-operational-data:v1"


def load_operational_data_properties(aas_path: str = AAS_PATH, profile_id: str = PROFILE_ID) -> list[dict]:
    """
    Return the Property elements of whichever submodel in aas_path declares,
    at the submodel level, that it conforms to profile_id.

    Matched by semanticId, not by idShort: idShort is just a human label and
    is allowed to differ per device (CncOperationalData vs
    GrindOperationalData) -- the submodel-level semanticId is what
    "conforms to this profile" actually means.
    """
    with open(aas_path, "r", encoding="utf-8") as f:
        env = json.load(f)

    for submodel in env["submodels"]:
        keys = submodel.get("semanticId", {}).get("keys", [])
        semantic_id = keys[0]["value"] if keys else None
        if semantic_id == profile_id:
            return [
                el for el in submodel["submodelElements"]
                if el["modelType"] == "Property"
            ]
    raise KeyError(f"No submodel conforming to profile {profile_id!r} found in {aas_path}")
