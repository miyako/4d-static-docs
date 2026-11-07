"""Download and verify the static-docs release contract before extracting HTML."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_assets(assets: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for line in (assets / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        if not match or match[2] in (".", "..", "SHA256SUMS"):
            raise ValueError(f"invalid checksum record: {line!r}")
        digest, name = match.groups()
        if name in hashes:
            raise ValueError(f"duplicate checksum for {name}")
        path = assets / name
        if not path.is_file() or sha256(path) != digest:
            raise ValueError(f"missing asset or SHA-256 mismatch: {name}")
        hashes[name] = digest
    if not {"docs.zip", "snapshot.json", "link-report.json"} <= hashes.keys():
        raise ValueError("checksums must cover docs.zip, snapshot.json and link-report.json")
    return hashes


def validate_manifest(manifest: dict, hashes: dict[str, str]) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("snapshot manifest must be an object")
    if manifest.get("schemaVersion") != 1 or manifest.get("archiveRoot") != "docs":
        raise ValueError("unsupported static snapshot schema or archive root")
    if not isinstance(manifest.get("sourceRepository"), str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", manifest["sourceRepository"]
    ):
        raise ValueError("snapshot sourceRepository must be owner/repository")
    if not isinstance(manifest.get("sourceCommit"), str) or not re.fullmatch(r"[0-9a-f]{40}", manifest["sourceCommit"]):
        raise ValueError("snapshot sourceCommit must be a full commit SHA")
    if not isinstance(manifest.get("generatorCommit"), str) or not re.fullmatch(r"[0-9a-f]{40}", manifest["generatorCommit"]):
        raise ValueError("snapshot generatorCommit must be a full commit SHA")
    if not isinstance(manifest.get("htmlPages"), int) or manifest["htmlPages"] <= 0:
        raise ValueError("snapshot htmlPages must be positive")
    capture = manifest.get("syntaxCapture")
    if capture is not None:
        if not isinstance(capture, dict) or capture.get("asset") != "syntaxEN.json":
            raise ValueError("unsupported syntax capture asset")
        if not all(isinstance(capture.get(key), str) and capture[key] for key in ("version", "build")):
            raise ValueError("syntax capture requires version and build provenance")
        if hashes.get("syntaxEN.json") != capture.get("sha256"):
            raise ValueError("syntax capture hash does not match verified release asset")
    elif "syntaxEN.json" in hashes:
        raise ValueError("syntax asset present but not declared in snapshot")


def unpack(assets: Path, destination: Path, manifest: dict) -> None:
    """Preflight the entire ZIP before writing; never follow archive links."""
    with zipfile.ZipFile(assets / "docs.zip") as archive:
        names = set()
        paths: dict[PurePosixPath, bool] = {}
        size = 0
        entries = archive.infolist()
        if len(entries) > 200_000:
            raise ValueError("static archive exceeds 200,000 entries")
        for entry in entries:
            name = entry.filename
            path = PurePosixPath(name)
            mode = entry.external_attr >> 16
            if (
                "\\" in name or "\x00" in name or ":" in name or path.is_absolute()
                or any(part in (".", "..") for part in name.rstrip("/").split("/"))
                or str(path) != name.rstrip("/") or path in paths
                or not (name == "snapshot.json" or name.startswith("docs/"))
                or stat.S_ISLNK(mode)
                or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)
                or entry.flag_bits & 1
            ):
                raise ValueError(f"unsafe or duplicate archive entry: {name!r}")
            names.add(name)
            paths[path] = entry.is_dir()
            size += entry.file_size
        for path in paths:
            if any(parent in paths and not paths[parent] for parent in path.parents):
                raise ValueError(f"archive file/directory conflict: {path}")
        if size > 16 * 1024**3:
            raise ValueError("static archive exceeds 16 GiB uncompressed")
        if "snapshot.json" not in names:
            raise ValueError("archive is missing snapshot.json")
        if archive.getinfo("snapshot.json").file_size > 1024 * 1024:
            raise ValueError("archive snapshot manifest exceeds 1 MiB")
        if archive.read("snapshot.json") != (assets / "snapshot.json").read_bytes():
            raise ValueError("archive and release snapshot manifests differ")
        html_count = sum(not e.is_dir() and e.filename.endswith(".html") for e in entries)
        if html_count != manifest["htmlPages"]:
            raise ValueError("archive HTML count does not match snapshot manifest")
        destination.mkdir()
        for entry in entries:
            target = destination / entry.filename
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)


def download(repository: str, tag: str, destination: Path) -> tuple[dict, dict]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("release repository must be owner/repository")
    if not tag or tag.startswith("-"):
        raise ValueError("release tag must be explicit and must not start with '-'")
    if destination.exists():
        raise ValueError(f"release destination already exists: {destination}")
    release = json.loads(subprocess.check_output([
        "gh", "release", "view", tag, "--repo", repository,
        "--json", "tagName,url,assets",
    ], text=True))
    names = {asset["name"] for asset in release["assets"]}
    required = {"docs.zip", "snapshot.json", "link-report.json", "SHA256SUMS"}
    if not required <= names:
        raise ValueError(f"release missing required assets: {sorted(required - names)}")
    selected = required | ({"syntaxEN.json"} & names)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".static-release-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        assets = staging / "assets"
        assets.mkdir()
        command = ["gh", "release", "download", tag, "--repo", repository, "--dir", str(assets)]
        for name in sorted(selected):
            command.extend(["--pattern", name])
        subprocess.run(command, check=True)
        hashes = verify_assets(assets)
        manifest = json.loads((assets / "snapshot.json").read_text(encoding="utf-8"))
        validate_manifest(manifest, hashes)
        unpack(assets, staging / "site", manifest)
        release_provenance = {
            "repository": repository, "tag": release["tagName"], "url": release["url"],
            "sha256": hashes,
            "checksumsSha256": sha256(assets / "SHA256SUMS"),
            "assets": [asset for asset in release["assets"] if asset["name"] in selected],
        }
        (staging / "release.json").write_text(
            json.dumps(release_provenance, indent=2) + "\n", encoding="utf-8"
        )
        staging.rename(destination)
    return manifest, release_provenance
