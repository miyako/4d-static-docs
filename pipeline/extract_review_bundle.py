#!/usr/bin/env python3
"""Run only deterministic extraction stages, in a fresh review-bundle directory."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from common.docsroot import resolve_docs_root
import release_snapshot


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def changes(old: dict, new: dict) -> dict:
    return {
        "added": sorted(new.keys() - old.keys()),
        "removed": sorted(old.keys() - new.keys()),
        "changed": sorted(key for key in old.keys() & new.keys() if old[key] != new[key]),
        "unchanged": sorted(key for key in old.keys() & new.keys() if old[key] == new[key]),
    }


def manifest_hashes(manifest: dict) -> dict:
    return {entry["id"]: entry["contentHash"] for entry in manifest["entries"]}


def sections(pages: dict) -> dict:
    return {
        f"{class_name}:{section['headingKey']}": section
        for class_name, page in pages.items()
        for section in page["sections"]
    }


def git_commit(path: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()


def inside_repo(repo: Path, value: str) -> Path:
    path = (repo / value).resolve()
    if not path.is_relative_to(repo):
        raise ValueError(f"path must be inside the repository: {value}")
    return path


def extract(args: argparse.Namespace, provenance: dict, output: Path) -> None:
    repo = Path(args.repo_root).resolve()
    if args.release_tag:
        source = inside_repo(repo, args.release_source)
        if source == repo or source == output or source.is_relative_to(output) or output.is_relative_to(source):
            raise ValueError("release source must be separate from the repository root and review output")
        manifest, release = release_snapshot.download(args.release_repo, args.release_tag, source)
        provenance["release"] = release
        provenance["staticSnapshot"] = manifest
        write_json(output / "snapshot.json", manifest)
        write_json(output / "release.json", release)
        tree = source / "site/docs"
        capture = manifest.get("syntaxCapture")
        if capture:
            if args.syntax_json or args.syntax_version or args.syntax_build:
                raise ValueError("bundled capture metadata must not be overridden by syntax options")
            args.syntax_json = str((source / "assets/syntaxEN.json").relative_to(repo))
            args.syntax_version = capture["version"]
            args.syntax_build = capture["build"]
        elif not args.syntax_json or not args.syntax_version:
            raise ValueError("release has no syntax capture; supply --syntax-json and --syntax-version")
    else:
        tree = inside_repo(repo, args.docs_tree)
    args.syntax_json = args.syntax_json or "references/syntaxEN.json"
    args.syntax_version = args.syntax_version or "21-R3"
    syntax = inside_repo(repo, args.syntax_json)
    docs = resolve_docs_root(tree, None if args.version == "auto" else args.version).resolve()
    if not docs.is_relative_to(tree):
        raise ValueError("version must select a directory inside the static docs tree")
    if not list((docs / "commands").glob("*.html")):
        raise ValueError(f"no command HTML pages found under {docs}")
    if not list((docs / "API").glob("*.html")):
        raise ValueError(f"no API HTML pages found under {docs}")
    syntax_doc = read_json(syntax)
    if not isinstance(syntax_doc, dict) or not any(
        isinstance(value, dict) and key not in ("_command_", "4D")
        for key, value in syntax_doc.items()
    ):
        raise ValueError("syntax capture has no OOP classes")

    provenance.update({
        "repositoryCommit": git_commit(repo),
        "staticSnapshotCommit": None if args.release_tag else git_commit(tree),
        "docsRoot": str(docs.relative_to(repo)),
        "docsVersion": docs.name,
        "syntaxSource": {
            "path": str(syntax.relative_to(repo)),
            "sha256": hashlib.sha256(syntax.read_bytes()).hexdigest(),
            "declaredDocsVersion": args.syntax_version,
            "build": args.syntax_build or None,
            "matchesDocsVersion": args.syntax_version == docs.name,
        },
        "pythonVersion": sys.version,
        "dependencies": {
            name: importlib.metadata.version(name) for name in ("beautifulsoup4", "lxml")
        },
    })
    write_json(output / "provenance.json", provenance)

    # Baselines stay read-only; no ledger, overlay, assembled IR or verified
    # example is copied into the bundle or rewritten by these stages.
    old_classic = read_json(repo / "out/manifest.json")
    old_oop = read_json(repo / "out/oop_manifest.json")
    old_pages = read_json(repo / "out/oop_stage1_raw.json")
    write_json(output / "baseline.json", {
        "classicManifest": old_classic,
        "oopManifest": old_oop,
        "oopPages": {
            name: {"docPage": page["docPage"], "contentHash": page["contentHash"]}
            for name, page in old_pages.items()
        },
    })

    def artifact(name: str) -> str:
        return str((output / name).relative_to(repo))

    def run(script: str, *options: str) -> None:
        command = [
            sys.executable, str(repo / "pipeline" / script), "--repo-root", str(repo),
            *options,
        ]
        log = output / "logs" / (Path(script).stem + ("_oop" if script.startswith("oop/") else "") + ".log")
        print(f"Running {script}", flush=True)
        with log.open("w", encoding="utf-8") as stream:
            result = subprocess.run(command, cwd=repo, stdout=stream, stderr=subprocess.STDOUT)
        print(log.read_text(encoding="utf-8"), end="", flush=True)
        provenance["stages"].append({"script": script, "exitCode": result.returncode})
        write_json(output / "provenance.json", provenance)
        if result.returncode:
            raise RuntimeError(f"{script} failed with exit code {result.returncode}; see {log}")

    docs_options = ("--docs-root", str(docs))
    syntax_options = ("--syntax-json", str(syntax.relative_to(repo)))
    run("stage0_manifest.py", *docs_options, "--out", artifact("manifest.json"))
    classic = read_json(output / "manifest.json")
    write_json(output / "classic_changes.json", changes(
        manifest_hashes(old_classic), manifest_hashes(classic)
    ))
    if not classic["entries"]:
        raise ValueError("classic manifest is empty; check the HTML layout")
    run("stage1_extract.py", "--manifest", artifact("manifest.json"),
        "--out", artifact("stage1_raw.json"), "--force",
        "--cache-dir", artifact("cache/classic"))
    raw = read_json(output / "stage1_raw.json")
    if raw["failures"] or {r["id"] for r in raw["records"]} != {
        entry["id"] for entry in classic["entries"]
    }:
        raise ValueError("classic extraction is incomplete; see stage1_raw.json failures")
    run("stage2_candidates.py", "--stage1", artifact("stage1_raw.json"),
        "--out", artifact("candidates.json"))

    run("oop/stage0_reconcile.py", *docs_options, *syntax_options,
        "--out", artifact("oop_source_diff.json"))
    run("oop/stage0_manifest.py", *docs_options, *syntax_options,
        "--syntax-version", args.syntax_version, "--out", artifact("oop_manifest.json"))
    oop = read_json(output / "oop_manifest.json")
    write_json(output / "oop_changes.json", changes(
        manifest_hashes(old_oop), manifest_hashes(oop)
    ))
    run("oop/stage1_extract.py", *docs_options, "--no-cache",
        "--cache-dir", artifact("cache/oop"), "--out", artifact("oop_stage1_raw.json"))
    pages = read_json(output / "oop_stage1_raw.json")
    if not pages or not sections(pages):
        raise ValueError("OOP extraction is empty; check the API HTML layout")
    write_json(output / "oop_page_changes.json", changes(
        {key: page["contentHash"] for key, page in old_pages.items()},
        {key: page["contentHash"] for key, page in pages.items()},
    ))
    write_json(output / "oop_section_changes.json", changes(sections(old_pages), sections(pages)))
    run("oop/stage2_signatures.py", *syntax_options,
        "--out", artifact("oop_signatures.json"), "--report", artifact("oop_roundtrip_report.json"))
    run("oop/stage2b_crosscheck.py", *syntax_options,
        "--signatures", artifact("oop_signatures.json"), "--raw", artifact("oop_stage1_raw.json"),
        "--out", artifact("oop_param_conflicts.json"))
    provenance["status"] = "extracted_review_required"


def summary(output: Path, provenance: dict) -> None:
    lines = [
        "# Documentation extraction",
        "",
        f"Status: **{provenance['status']}**",
        "",
        "Raw review inputs only. No semantic approval, compiler verification, "
        "assembled corpus, or CLI publication was performed.",
        "",
    ]
    if "error" in provenance:
        lines.extend(["Extraction failed; see `provenance.json` and `logs/` for diagnostics.", ""])
    if "docsVersion" in provenance:
        lines.extend([
            f"HTML version: `{provenance['docsVersion']}`",
            f"Pipeline/baseline commit: `{provenance['repositoryCommit']}`",
            f"Syntax capture version: `{provenance['syntaxSource']['declaredDocsVersion']}`",
            "",
        ])
        if provenance.get("release"):
            manifest = provenance["staticSnapshot"]
            lines.extend([
                f"Release: {provenance['release']['url']}",
                f"Upstream source commit: `{manifest['sourceCommit']}`",
                f"Snapshot generator commit: `{manifest['generatorCommit']}`",
                f"Archive SHA-256: `{provenance['release']['sha256']['docs.zip']}`",
                "",
            ])
        else:
            lines.extend([f"Static snapshot commit: `{provenance['staticSnapshotCommit']}`", ""])
        if not provenance["syntaxSource"]["matchesDocsVersion"]:
            lines.extend([
                "**Review required: HTML and syntax capture versions differ. "
                "HTML-only members are preserved in raw sections and the reconciliation report; "
                "the signature parser still uses the supplied capture.**",
                "",
            ])
    lines.extend(["| Change report | Added | Changed | Removed | Unchanged |",
                  "|---|---:|---:|---:|---:|"])
    for name in ("classic_changes", "oop_changes", "oop_page_changes", "oop_section_changes"):
        path = output / f"{name}.json"
        if path.exists():
            report = read_json(path)
            counts = [str(len(report[key])) for key in ("added", "changed", "removed", "unchanged")]
            lines.append(f"| `{name}.json` | " + " | ".join(counts) + " |")
    lines.extend([
        "",
        "HTML hashes include navigation/build changes; a changed hash is a review signal, "
        "not proof of a changed signature. OOP section deltas compare extracted member content.",
        "",
    ])
    for name, fields in (
        ("stage1_raw.json", ("parseWarnings", "failures")),
        ("oop_source_diff.json", ("syntaxen_missing", "doc_missing")),
        ("oop_param_conflicts.json", ("conflicts",)),
    ):
        path = output / name
        if path.exists():
            report = read_json(path)
            values = report.get("counts", report)
            lines.append(f"`{name}`: " + ", ".join(f"{key}={values[key]}" for key in fields))
    lines.extend([
        "",
        "Review parse warnings, skipped pages, source reconciliation, and parameter conflicts "
        "before proceeding to semantic assembly.",
        "",
    ])
    (output / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--docs-tree", help="Generated static docs directory inside the repository")
    source.add_argument("--release-tag", help="Explicit versioned static-docs release tag")
    parser.add_argument("--release-repo", default="miyako/4d-static-docs")
    parser.add_argument("--release-source", default="static-release", help="Fresh verified download directory inside repository")
    parser.add_argument("--version", default="auto")
    parser.add_argument("--syntax-json")
    parser.add_argument("--syntax-version")
    parser.add_argument("--syntax-build", default="", help="4D build that supplied the capture")
    parser.add_argument("--output", default="extraction", help="Fresh directory inside the repository")
    args = parser.parse_args()
    repo = Path(args.repo_root).resolve()
    output = inside_repo(repo, args.output)
    # Reject reused output directories rather than mixing old success artifacts
    # into a partial or failed run.
    output.mkdir(parents=True, exist_ok=False)
    (output / "logs").mkdir()
    provenance = {"status": "running", "stages": []}
    try:
        extract(args, provenance, output)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        provenance["status"] = "failed"
        provenance["error"] = str(exc)
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 1
    finally:
        write_json(output / "provenance.json", provenance)
        summary(output, provenance)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
