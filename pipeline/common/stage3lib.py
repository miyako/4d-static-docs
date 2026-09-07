"""Shared Stage 3 logic: mechanical draft -> overlay merge -> schema
validation. Used by both stage3_semantic.py (13 fixtures, diffed against
examples.json) and stage3_bulk.py (full-corpus rollout, ledger-tracked,
no ground truth to diff against).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from common.autoparse import draft_overload_params


def load_json(path: Path):
    with path.open() as f:
        return json.load(f)


def deep_merge(base, overlay):
    """Deep-merge `overlay` onto `base`; overlay wins on scalars/lists,
    dicts are merged key-by-key.
    """
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = dict(base)
        for k, v in overlay.items():
            merged[k] = deep_merge(base.get(k), v) if k in base else v
        return merged
    return overlay if overlay is not None else base


def first_sentence(text: str | None) -> str | None:
    if not text:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    m = re.match(r"(.{10,220}?[.!?])(\s|$)", text)
    return (m.group(1) if m else text[:220]).strip()


def build_draft_entry(record: dict) -> tuple[dict, list[str], list[str]]:
    """Build a mechanical draft CommandEntry from a Stage 1 raw record.

    Returns (entry, review_notes, signature_texts) -- signature_texts is
    the raw signature line for each draft overload, in the same order, so
    callers can log which doc syntax variant fed which overload index
    (needed to report overload merges intelligibly).
    """
    review_notes: list[str] = []
    description = record.get("sections", {}).get("description", {}).get("text")
    role_guess = first_sentence(description)
    if role_guess is None:
        review_notes.append("no description section found; semanticRole left unset")

    overloads = []
    signature_texts = []
    for sig in record.get("signatureLines", []):
        elements, notes, returns = draft_overload_params(sig["text"])
        for n in notes:
            review_notes.append(f"signature {sig['text']!r}: {n}")
        overload = {"params": elements}
        if returns is not None:
            overload["returns"] = returns
        if role_guess:
            overload["semanticRole"] = role_guess
        overloads.append(overload)
        signature_texts.append(sig["text"])
    if len(overloads) > 1:
        review_notes.append(
            f"{len(overloads)} overloads share one auto-derived semanticRole; "
            "needs a per-overload overlay (overloadPatches/overloadMerges) to actually discriminate them"
        )

    entry = {
        "id": record["id"],
        "displayName": record["displayName"],
        "kind": "classic_command",
        "theme": record.get("theme") or "",
        "overloads": overloads,
    }
    return entry, review_notes, signature_texts


def apply_overload_merges(overloads: list[dict], signature_texts: list[str], merges: list[dict] | None):
    """Collapse draft overloads that are really one semantic overload split
    across multiple doc syntax lines (e.g. an optional leading '*' rendered
    as its own line). Returns (new_overloads, merge_log).
    """
    if not merges:
        return overloads, []

    consumed: set[int] = set()
    merged_overloads: list[dict] = []
    merge_log: list[dict] = []
    for merge in merges:
        idxs = merge["sourceIndices"]
        consumed.update(idxs)
        replacement = {"params": merge["params"]}
        for optional_field in ("returns", "semanticRole", "interactionNotes", "mechanism", "discriminatedBy"):
            if optional_field in merge:
                replacement[optional_field] = merge[optional_field]
        merged_overloads.append(replacement)
        merge_log.append({
            "merged_source_indices": idxs,
            "merged_source_signatures": [signature_texts[i] for i in idxs if i < len(signature_texts)],
            "into_overload_index": len(merged_overloads) - 1,
            "note": merge.get("note", ""),
        })

    for i, ov in enumerate(overloads):
        if i not in consumed:
            merged_overloads.append(ov)

    return merged_overloads, merge_log


def apply_overload_patches(overloads: list[dict], patches: list[dict] | None) -> list[dict]:
    """Patch individual overloads in place by index (e.g. to give a
    multi-overload command distinct semanticRole/discriminatedBy per
    overload) without restructuring params the way a merge does.
    """
    if not patches:
        return overloads
    overloads = list(overloads)
    for patch in patches:
        idx = patch["index"]
        if 0 <= idx < len(overloads):
            fields = {k: v for k, v in patch.items() if k != "index"}
            overloads[idx] = deep_merge(overloads[idx], fields)
    return overloads


def apply_overlay(entry: dict, signature_texts: list[str], overlay_path: Path):
    """Apply a hand/agent-authored overlay:
      1. collapse any overloadMerges (structural: N syntax lines -> 1 overload)
      2. apply any overloadPatches (per-index field corrections)
      3. deep-merge every other top-level field (data-only corrections/additions)
    Returns (merged_entry, merge_log).
    """
    if not overlay_path.exists():
        return entry, []
    overlay = load_json(overlay_path)
    merges = overlay.pop("overloadMerges", None)
    patches = overlay.pop("overloadPatches", None)
    merged_overloads, merge_log = apply_overload_merges(entry["overloads"], signature_texts, merges)
    merged_overloads = apply_overload_patches(merged_overloads, patches)
    entry = dict(entry, overloads=merged_overloads)
    return deep_merge(entry, overlay), merge_log
