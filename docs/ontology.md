# Siemens asset ontology → AIO integration (local test)

This demonstrates how a Siemens-side asset ontology for the CNC machine
flows into Azure IoT Operations, and gives you a way to test that mapping
without a real Siemens IE device or a live AIO cluster.

## Three layers, not two

```
Siemens ontology          AIO capability model         AIO ingestion config
┌───────────────────┐     ┌───────────────────┐       ┌───────────────────┐
│ AAS submodel       │ ─▶ │ WoT Thing          │  ─▶  │ AIO Asset CRD     │
│ aas_cnc_submodel   │     │ Description        │       │ asset-cnc-001.yaml│
│ .json              │     │ cnc-001.td.json    │       │                   │
└───────────────────┘     └───────────────────┘       └───────────────────┘
   generate_wot_td.py ─┘        generate_aio_asset.py ─┘
```

Azure IoT Operations' connector framework (Akri) doesn't read a vendor
ontology directly — it resolves what a device/asset exposes against a
**W3C Web of Things (WoT) Thing Description**, then the Asset resource
selects which of those properties to actually ingest and where to send them.
So the pipeline here has a middle layer on purpose: the Siemens ontology and
the AIO asset never talk to each other directly, they agree through that
shared, protocol-neutral capability model.

### Layer 1 — AAS (the Siemens ontology)

Siemens describes its Industrial Edge / Industry 4.0 assets using the
**Asset Administration Shell (AAS)**, the IEC 63278 standard for
machine-readable digital twins. `ontology/aas_cnc_submodel.json` defines an
AAS environment for `CNC-001`:

- **Nameplate** submodel — ZVEI Digital Nameplate fields (manufacturer,
  product designation, serial number).
- **CncOperationalData** submodel — one AAS `Property` per telemetry tag the
  IE S7 Connector publishes on `ie/cnc` (motor speed, spindle load, tool
  temperature, OEE, fault code, etc.), each with a `semanticId`, `valueType`,
  and unit.

`DemoPhase` is deliberately left out of the ontology — it's a simulator-only
diagnostic field, not a real asset property, and is tracked as an explicit
exclusion rather than silently ignored.

### Layer 2 — WoT Thing Description (what AIO actually reads)

`ontology/generate_wot_td.py` reads the AAS submodel and generates
`ontology/cnc-001.td.json`, a WoT Thing Description: one `PropertyAffordance`
per AAS property, each with a `type` (WoT's `number`/`integer`/`boolean`/
`string`), `unit`, and an MQTT `form` describing where to observe it.

The AAS → WoT link is provable, not asserted: each WoT property's `@type`
carries the *exact same* `semanticId` URN as its AAS source property, via a
`siemens:` JSON-LD context prefix. `ontology/test_ontology_mapping.py`
checks this directly — if the two ever disagree on a name, type, or unit for
the same tag, the test fails and names the property.

### Layer 3 — AIO Asset (what actually gets ingested)

`ontology/generate_aio_asset.py` reads the WoT TD (not the AAS file) and
generates `k8s/asset-cnc-001.yaml`, an Azure IoT Operations `Asset` resource
with one `dataPoint` per WoT property affordance. This is illustrative: AIO's
native `Asset`/`AssetEndpointProfile` CRDs (`deviceregistry.microsoft.com`)
target OPC UA, media, and REST connectors most directly today — a raw-MQTT
source like this simulator would normally be onboarded through a Dataflow
with a JSON-path transform rather than a first-class Asset `dataPoint`. The
generated YAML shows what the equivalent semantic mapping looks like either
way, keyed off the same WoT TD.

## Regenerating

Regenerate both layers after editing the ontology, in order:

```bash
python ontology/generate_wot_td.py
python ontology/generate_aio_asset.py
```

## Running the test

`ontology/test_ontology_mapping.py` checks, entirely locally:

1. The AAS submodel is structurally valid (every property has a
   `semanticId`, `valueType`, and unit where applicable).
2. The WoT TD carries every AAS property across losslessly — same name,
   same `semanticId` (as `@type`), same value type, same unit — and the
   checked-in `cnc-001.td.json` is up to date with the AAS source.
3. Every field the simulator (`simulator/simulate_ie_cnc.py`) actually
   publishes has a matching WoT property, or is on the explicit exclusion
   list — this is what catches ontology/telemetry drift, e.g. a new tag
   added to the simulator that was never added to the ontology.
4. The generated `k8s/asset-cnc-001.yaml` has one `dataPoint` per WoT
   property, each `dataSource` resolves against a real simulator payload,
   and the checked-in YAML is up to date with the TD.

```bash
python -m unittest ontology.test_ontology_mapping -v
```

All checks run against the simulator's actual output, so if you change a
telemetry field name or type in `simulate_ie_cnc.py` without updating the
ontology, the test fails and tells you exactly which property drifted —
and exactly which layer (AAS↔WoT vs. WoT↔AIO vs. WoT↔simulator) it drifted
in.
