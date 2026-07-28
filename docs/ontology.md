# Siemens asset ontology → AIO integration (local test)

This demonstrates how a shared Siemens-side asset **profile** flows into
Azure IoT Operations for two genuinely different devices — one clean, one
messy — and gives you a way to test that mapping without real hardware or a
live AIO cluster.

## Why two devices

A single well-behaved device makes for an unconvincing demo: if the
simulator already emits field names that match the ontology 1:1, applying
the ontology looks like renaming a tag, not solving a real problem. So this
build has two:

| Device | What it is | Raw tags |
|---|---|---|
| **CNC-001** | Modern Siemens IE-connected CNC | Already friendly — `MotorSpeed_RPM`, `ToolTemperature_C`, etc. Needs no binding. |
| **GRIND-077** | Legacy S7-300 grinding cell, no IE Databus | Cryptic PLC addresses (`DB10.DBD4`, `MW102`, `M20.1`...), inconsistent units — a scaled integer, Fahrenheit, a 0/1 flag, a 0..1 fraction. |

Both are asserted, and tested, to resolve into the **identical canonical
shape** — same property names, same types, same units — because both
conform to the same profile. That's the actual claim this repo backs up:
not "we can rename a tag," but "a legacy machine with none of the modern
conveniences normalizes the same way a modern one does, given a profile."

## Four layers, not three

```
Shared profile                Siemens ontology            AIO capability model      AIO ingestion config
┌─────────────────────┐      ┌───────────────────┐      ┌───────────────────┐     ┌────────────────────┐
│ machine_operational_ │ ◀── │ AAS submodel        │ ──▶ │ WoT Thing          │ ──▶ │ AIO Asset CRD       │
│ data_profile.json    │ conforms │ per device         │     │ Description        │     │ per device          │
│ (canonical shape)    │      │ + binding if messy  │     │ <device>.td.json   │     │ asset-<device>.yaml │
└─────────────────────┘      └───────────────────┘      └───────────────────┘     └────────────────────┘
                                        generate_wot_td.py ─┘   generate_aio_asset.py ─┘
```

Azure IoT Operations' connector framework (Akri) doesn't read a vendor
ontology directly — it resolves what a device/asset exposes against a
**W3C Web of Things (WoT) Thing Description**. So the pipeline has a middle
layer on purpose: the Siemens ontology and the AIO asset never talk to each
other directly, they agree through that shared, protocol-neutral capability
model — and, one level up, both devices agree with *each other* only
because they both conform to the same profile.

### Layer 0 — the profile (the reusable contract)

`ontology/profiles/machine_operational_data_profile.json` is an AAS
Submodel Template (an IDTA-style "profile"): the canonical property list —
`MotorSpeed_RPM`, `SpindleLoad_Pct`, `FeedRate_mm_min`, `ToolTemperature_C`,
`PartCount`, `FaultCode`, `RunningStatus`, `OEE_Pct` — each with a
`semanticId`, `valueType`, and unit, and nothing device-specific. Any device
that wants AIO to understand it declares, at the *submodel level*, that it
conforms to this profile's `id`
(`urn:siemens:ie:profile:machine-operational-data:v1`).

### Layer 1 — AAS (each device's instance of the profile)

`ontology/aas_cnc_submodel.json` and `ontology/aas_grind077_submodel.json`
each contain a **Nameplate** submodel (ZVEI Digital Nameplate — manufacturer,
product, serial) plus an operational-data submodel that conforms to the
shared profile above. `DemoPhase`, a CNC-001 simulator-only diagnostic
field, is deliberately left out of the ontology and tracked as an explicit
exclusion rather than silently ignored.

Conformance is matched by `semanticId`, not by name — `CncOperationalData`
and `GrindOperationalData` are allowed to be called different things,
because what actually makes them interchangeable to AIO is that every
property inside carries the identical profile `semanticId`.

### The binding — where the hard problem actually gets solved

CNC-001 needs no binding file: its simulator already speaks the profile's
language, so the generators default every property to `rawField == idShort`,
`transform == "identity"`. GRIND-077 does need one —
`ontology/bindings/grind077_binding.json` declares, per canonical property,
which raw S7 tag to read and which named transform
(`ontology/transforms.py`: `divide_10`, `fahrenheit_to_celsius`,
`int_to_bool`, `fraction_to_percent`, or `identity`) reconciles its raw
representation with the profile's declared unit and type.

### Layer 2 — WoT Thing Description (what AIO actually reads)

`ontology/generate_wot_td.py <device>` reads a device's AAS submodel and its
binding, and generates `ontology/<device>.td.json`: one `PropertyAffordance`
per profile property, each with a `type`, `unit`, and an MQTT `form` that
carries both the raw field it reads (`siemens:jsonPath`, bracket-escaped
when the raw tag itself contains a dot, e.g. `DB10.DBD4`) and the transform
that resolves it (`siemens:transform`).

The AAS → WoT link is provable, not asserted: each WoT property's `@type`
carries the *exact same* `semanticId` URN as its AAS source property.
`ontology/test_ontology_mapping.py` checks this directly, for both devices —
if either ever disagrees on a name, type, or unit for the same tag, the test
fails and names the property and the device.

### Layer 3 — AIO Asset (what actually gets ingested)

`ontology/generate_aio_asset.py <device>` reads the WoT TD (not the AAS
file) and generates `k8s/asset-<device>.yaml`, an Azure IoT Operations
`Asset` resource with one `dataPoint` per WoT property affordance. Where a
device's raw representation doesn't match the profile, the generated YAML
carries a comment noting which transform a Dataflow would need to apply.
This is illustrative: AIO's native `Asset`/`AssetEndpointProfile` CRDs
(`deviceregistry.microsoft.com`) target OPC UA, media, and REST connectors
most directly today — a raw-MQTT source like these simulators would normally
be onboarded through a Dataflow with a JSON-path transform rather than a
first-class Asset `dataPoint`.

## Regenerating

Regenerate both generated layers, per device, after editing the ontology:

```bash
python ontology/generate_wot_td.py cnc001
python ontology/generate_aio_asset.py cnc001

python ontology/generate_wot_td.py grind077
python ontology/generate_aio_asset.py grind077
```

## Seeing the mapping resolve against a live value

The test suite (below) proves the mapping is consistent; it doesn't show you
what it produces. `ontology/show_live_mapping.py <device>` does — it takes
one real raw payload from that device's simulator and, for every property,
prints the raw field, the raw value, the transform applied, and the
resolved value:

```bash
python ontology/show_live_mapping.py cnc001
python ontology/show_live_mapping.py grind077
```

Run both back to back — same canonical dataPoint names and units come out
both times, despite completely different raw inputs on the GRIND-077 side.

## Running the test

`ontology/test_ontology_mapping.py` checks, entirely locally, across both
devices:

1. Each AAS submodel is structurally valid.
2. Both devices genuinely conform to the same profile — same submodel-level
   `semanticId`, same canonical property set, same type/unit/`semanticId`
   per property.
3. The premise itself: GRIND-077's raw payload contains none of the
   canonical names (otherwise the binding wouldn't be proving anything), and
   CNC-001's does.
4. Each WoT TD carries its AAS ontology across losslessly, and is up to date
   on disk.
5. Applying each device's binding + transform to a real raw payload resolves
   every property to a value matching the ontology's declared type — the
   check that a `fahrenheit_to_celsius` or `divide_10` transform is actually
   correct, not just present.
6. Each generated `k8s/asset-<device>.yaml` has one `dataPoint` per WoT
   property, resolving against a live raw payload, and is up to date on disk.

```bash
python -m unittest ontology.test_ontology_mapping -v
```

14 tests. All checks run against each simulator's actual output, so if you
change a raw tag name, a transform, or a telemetry field without updating
the corresponding ontology piece, the test fails and tells you exactly which
property, on which device, and at which layer (profile↔AAS, AAS↔WoT,
binding↔transform, or WoT↔AIO) it drifted in.
