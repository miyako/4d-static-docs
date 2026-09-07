#!/usr/bin/env python3
"""Stage 5: assemble the final root 4D Command IR document.

Merges:
  - the 14 hand-authored fixture commands + their Layer-2 registries
    (references/4d-command-ir-examples.json)
  - the 1443 bulk-extracted command entries (out/stage3_ir_full/*.json)
  - the three standalone Layer-2 registries built during Stage 3 review
    (4d-command-ir-enums.json, 4d-command-ir-callbacks.json,
     4d-command-ir-foreign-grammars.json)

into a single root document, then validates it against
references/4d-command-ir-schema.json.

Usage:
    python3 stage5_assemble.py [--out PATH]
"""
import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFS = ROOT / "references"
OUT_DIR = ROOT / "out" / "stage3_ir_full"
DEFAULT_OUTPUT = ROOT / "out" / "4d-command-ir.json"

LAYER2_MAPS = ["enums", "subGrammars", "foreignGrammars", "handleTypes", "callbackContracts"]
STANDALONE_REGISTRIES = {
    "enums": "4d-command-ir-enums.json",
    "callbackContracts": "4d-command-ir-callbacks.json",
    "foreignGrammars": "4d-command-ir-foreign-grammars.json",
}


def load_json(path):
    with open(path) as f:
        return json.load(f)


def strip_meta(d):
    """Drop non-schema bookkeeping keys (e.g. '_source') from a registry map."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


def merge_registry_map(root, key, addition):
    existing = root.setdefault(key, {})
    for name, entry in addition.items():
        if name in existing and existing[name] != entry:
            raise SystemExit(f"Conflicting '{key}' registry entry for key '{name}'")
        existing[name] = entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="Output path for the assembled root IR document")
    args = parser.parse_args()

    fixtures_doc = load_json(REFS / "4d-command-ir-examples.json")

    root = {}
    for key in LAYER2_MAPS:
        root[key] = dict(fixtures_doc.get(key, {}))
    root["protocols"] = json.loads(json.dumps(fixtures_doc.get("protocols", {})))  # deep copy

    # Merge in the three standalone registries built during Stage 3 review.
    for key, filename in STANDALONE_REGISTRIES.items():
        addition = strip_meta(load_json(REFS / filename))
        merge_registry_map(root, key, addition)

    # Commands: 14 fixtures + 1443 bulk-extracted entries.
    fixture_commands = fixtures_doc.get("commands", [])
    bulk_files = sorted(glob.glob(str(OUT_DIR / "*.json")))
    bulk_commands = [load_json(f) for f in bulk_files]

    fixture_ids = {c["id"] for c in fixture_commands}
    bulk_ids = {c["id"] for c in bulk_commands}
    overlap = fixture_ids & bulk_ids
    if overlap:
        raise SystemExit(f"Duplicate command ids between fixtures and bulk corpus: {sorted(overlap)}")

    root["commands"] = fixture_commands + bulk_commands

    # Relationships: only the 14-fixture set exists (Stage 4 was explicitly skipped).
    root["relationships"] = fixtures_doc.get("relationships", [])

    # Validate against the schema.
    try:
        import jsonschema
    except ImportError:
        print("jsonschema not installed; skipping schema validation", file=sys.stderr)
    else:
        schema = load_json(REFS / "4d-command-ir-schema.json")
        validator_cls = jsonschema.Draft202012Validator if hasattr(jsonschema, "Draft202012Validator") else jsonschema.Draft7Validator
        validator = validator_cls(schema)
        errors = sorted(validator.iter_errors(root), key=lambda e: list(e.path))
        if errors:
            print(f"Schema validation FAILED with {len(errors)} error(s):", file=sys.stderr)
            for e in errors[:20]:
                print(f"  at {'/'.join(str(p) for p in e.path)}: {e.message}", file=sys.stderr)
            sys.exit(1)
        print("Schema validation: OK")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(root, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Assembled root IR document written to {out_path}")
    print(f"  commands: {len(root['commands'])} ({len(fixture_commands)} fixtures + {len(bulk_commands)} bulk)")
    for key in LAYER2_MAPS:
        print(f"  {key}: {len(root[key])}")
    print(f"  protocols.multiCallChains: {len(root['protocols'].get('multiCallChains', {}))}")
    print(f"  protocols.stateMachines: {len(root['protocols'].get('stateMachines', {}))}")
    print(f"  relationships: {len(root['relationships'])}")


if __name__ == "__main__":
    main()
