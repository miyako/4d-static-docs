#!/usr/bin/env python3
"""Parse 4D's localized-constants XLIFF corpus into a machine-readable enum registry.

Inputs (not committed as pipeline outputs -- copied from user-provided source files):
  pipeline/data/4D_ConstantsThemesEN.xlf  -- groupID -> theme/group display name
  pipeline/data/4D_ConstantsEN.xlf        -- groupID -> [{name, value}, ...] constants

Output:
  references/4d-constants-registry.json

  {
    "themes": {"<groupId>": "<theme name>", ...},
    "byTheme": {"<groupId>": [{"name": ..., "value": "..."}, ...], ...},
    "byName": {"<constant name>": [{"groupId": ..., "theme": ..., "value": "..."}, ...], ...}
  }

Notes:
  - `value` is kept as the raw XLIFF string (some are numeric, a few are string
    sentinels like "Lax"/"Strict"/"None" for Web SameSite, or absent groupID
    sub-lists reusing small integers like 0/1/2/3 for a different sub-concept
    within the same theme group) -- callers should not assume int().
  - A single theme/group commonly contains multiple logically-distinct
    constant lists that 4D's docs present as separate per-command enums (e.g.
    group 73 "Web Server" contains both the ~30 WEB SET OPTION selector
    constants AND the disjoint small-integer "Web debug log" sub-values AND a
    3-value "Web server database/host database/receiving request" list). This
    registry does not attempt to split those apart -- consumers should match
    by exact constant name (byName) rather than by "all values in theme X".
  - Constant names are NOT guaranteed globally unique across themes; byName
    maps to a list for that reason. In practice, doc-quoted constant names for
    a given command's selector table are unique enough for exact-match lookup.
"""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

D4_NS = "{http://www.4d.com}"

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parent / "data"
OUT_PATH = HERE.parent.parent / "references" / "4d-constants-registry.json"


def parse_themes(path):
    tree = ET.parse(path)
    themes = {}
    for tu in tree.getroot().iter("trans-unit"):
        gid = tu.get("id")
        target = tu.find("target")
        if gid is None or target is None or target.text is None:
            continue
        themes[gid] = target.text
    return themes


def parse_constants(path):
    tree = ET.parse(path)
    by_theme = {}
    for group in tree.getroot().iter("group"):
        gid = group.get(f"{D4_NS}groupID")
        if gid is None:
            continue
        entries = []
        for tu in group.findall("trans-unit"):
            value = tu.get(f"{D4_NS}value")
            target = tu.find("target")
            if target is None or target.text is None:
                continue
            entries.append({"name": target.text, "value": value})
        by_theme.setdefault(gid, []).extend(entries)
    return by_theme


def build_registry():
    themes = parse_themes(DATA_DIR / "4D_ConstantsThemesEN.xlf")
    by_theme = parse_constants(DATA_DIR / "4D_ConstantsEN.xlf")

    by_name = {}
    for gid, entries in by_theme.items():
        theme_name = themes.get(gid, f"<unknown theme {gid}>")
        for e in entries:
            by_name.setdefault(e["name"], []).append(
                {"groupId": gid, "theme": theme_name, "value": e["value"]}
            )

    registry = {"themes": themes, "byTheme": by_theme, "byName": by_name}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
    return registry


if __name__ == "__main__":
    reg = build_registry()
    n_themes = len(reg["themes"])
    n_constants = sum(len(v) for v in reg["byTheme"].values())
    print(f"Wrote {OUT_PATH} -- {n_themes} themes, {n_constants} constant entries")
