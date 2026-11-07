#!/usr/bin/env python3
"""Generate a pinned offline snapshot and portable release assets."""

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from offline import finalize, verify


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_commit(repository, ref):
    url = f"https://api.github.com/repos/{repository}/commits/{urllib.parse.quote(ref, safe='')}"
    request = urllib.request.Request(url, headers={"User-Agent": "4d-static-docs-regenerator"})
    with urllib.request.urlopen(request, timeout=60) as response:
        sha = json.load(response)["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError(f"Unexpected upstream commit: {sha}")
    return sha


def download_source(repository, commit, destination, workspace):
    archive = workspace / "source.tar.gz"
    run(["curl", "--fail", "--location", "--retry", "3", "--silent", "--show-error",
         f"https://codeload.github.com/{repository}/tar.gz/{commit}", "-o", str(archive)])
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if len(parts) <= 1:
                continue
            relative = Path(*parts[1:])
            if relative.is_absolute() or ".." in relative.parts or not (member.isfile() or member.isdir()):
                raise ValueError(f"Unsupported source archive entry: {member.name}")
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)


def crawl(urls, origin, output, log, base_path):
    pattern = "^" + re.escape(origin + base_path)
    command = [
        "wget", "--recursive", "--level=inf", "--convert-links", "--adjust-extension",
        "--page-requisites", "--no-parent", "--no-host-directories",
        "--execute", "robots=off", "--no-verbose", "--timeout=30", "--tries=3",
        "--accept-regex=" + pattern, "--output-file=" + str(log),
        "--directory-prefix=" + str(output),
    ]
    if isinstance(urls, Path):
        command += ["--input-file=" + str(urls)]
    else:
        command += urls
    result = subprocess.run(command)
    text = log.read_text(encoding="utf-8", errors="replace")
    errors = [line for line in text.splitlines() if "ERROR " in line]
    if result.returncode not in (0, 8) or any("ERROR 404:" not in line for line in errors):
        raise RuntimeError(f"Wget failed ({result.returncode}); see {log}")
    if result.returncode == 8 and not errors:
        raise RuntimeError(f"Wget reported an unclassified server error; see {log}")
    if errors:
        print(f"WARNING: {len(errors)} upstream 404 responses recorded in {log}", file=sys.stderr)
    return len(errors)


def pack(root, manifest, assets):
    archive = assets / "docs.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as out:
        out.write(manifest, "snapshot.json")
        for path in sorted(root.rglob("*")):
            if path.is_file():
                out.write(path, "docs/" + path.relative_to(root).as_posix())
    if archive.stat().st_size >= 2 * 1024**3:
        raise ValueError("docs.zip exceeds GitHub's 2 GiB release-asset limit")
    checksums = []
    for path in sorted(assets.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS":
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            checksums.append(f"{digest}  {path.name}\n")
    (assets / "SHA256SUMS").write_text("".join(checksums), encoding="ascii")


def generate(args):
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"Output already exists; choose a new staging path: {output}")
    generator_commit = args.generator_commit
    if not generator_commit:
        generator_commit = subprocess.check_output(
            ["git", "-C", str(Path(__file__).resolve().parents[2]), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", generator_commit):
        raise ValueError("--generator-commit must be a full 40-character commit SHA")
    capture_bytes = None
    if args.syntax_json:
        if not args.syntax_version or not args.syntax_build:
            raise ValueError("--syntax-json requires --syntax-version and --syntax-build")
        capture_bytes = args.syntax_json.read_bytes()
        if not isinstance(json.loads(capture_bytes), dict):
            raise ValueError("Syntax capture must be a JSON object")
    elif args.syntax_version or args.syntax_build:
        raise ValueError("Syntax metadata requires --syntax-json")
    for tool in ("curl", "wget", "npx"):
        if shutil.which(tool) is None:
            raise ValueError(f"Required command is missing: {tool}")
    commit = args.source_commit or resolve_commit(args.source_repo, args.source_ref)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("--source-commit must be a full 40-character commit SHA")
    output.mkdir(parents=True)
    logs = output / "logs"
    assets = output / "assets"
    logs.mkdir()
    assets.mkdir()
    prefix = args.base_path.strip("/")
    with tempfile.TemporaryDirectory(prefix="static-docs-", dir=args.work_directory) as temporary:
        workspace = Path(temporary)
        source = workspace / "source" / prefix
        source.mkdir(parents=True)
        if args.source_directory:
            shutil.copytree(args.source_directory, source, dirs_exist_ok=True)
        else:
            download_source(args.source_repo, commit, source, workspace)
        if not (source / "index.html").is_file():
            raise ValueError("Published source has no index.html")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        with (logs / "server.log").open("w") as server_log:
            server = subprocess.Popen(
                ["npx", "--yes", args.serve_package, "--listen", f"tcp://127.0.0.1:{port}",
                 "--no-clipboard", "--no-port-switching", "--no-request-logging", str(workspace / "source")],
                stdout=server_log, stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
            )
            try:
                url = origin + args.base_path
                deadline = time.monotonic() + args.startup_timeout
                while True:
                    if server.poll() is not None:
                        raise RuntimeError(f"Static server exited; see {logs / 'server.log'}")
                    try:
                        with urllib.request.urlopen(url, timeout=2) as response:
                            if response.status == 200:
                                break
                    except (urllib.error.URLError, TimeoutError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError(f"Static server did not become ready; see {logs / 'server.log'}")
                        time.sleep(0.2)
                downloaded = workspace / "downloaded"
                errors = crawl([url], origin, downloaded, logs / "wget.log", args.base_path)
                mirror = downloaded / prefix
                missing = [p.relative_to(source).as_posix() for p in source.rglob("*.html")
                           if not p.name.endswith(".html.html") and not (mirror / p.relative_to(source)).exists()]
                if missing:
                    seeds = workspace / "missing.txt"
                    seeds.write_text("".join(origin + args.base_path + urllib.parse.quote(name) + "\n"
                                             for name in sorted(missing)), encoding="utf-8")
                    errors += crawl(seeds, origin, downloaded, logs / "wget-extra.log", args.base_path)
            finally:
                if os.name != "nt":
                    import signal
                    try:
                        os.killpg(server.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                else:
                    server.terminate()
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    if os.name != "nt":
                        os.killpg(server.pid, signal.SIGKILL)
                    else:
                        server.kill()
                    server.wait()
        report = finalize(mirror, origin, args.public_origin, args.base_path)
        audit = verify(mirror, origin, source)
        report["upstream404Responses"] = errors
        write_json(assets / "link-report.json", report)
        snapshot = {
            "schemaVersion": 1,
            "sourceRepository": args.source_repo,
            "sourceRef": args.source_ref,
            "sourceCommit": commit,
            "publicOrigin": args.public_origin,
            "basePath": args.base_path,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "generatorCommit": generator_commit,
            "servePackage": args.serve_package,
            "archiveRoot": "docs",
            "htmlPages": audit["htmlPages"],
            "versionLabels": audit["versionLabels"],
            "unresolvedUpstreamPathCount": len(report["unresolvedUpstreamPaths"]),
            "syntaxCapture": None,
        }
        if args.syntax_json:
            capture = assets / "syntaxEN.json"
            capture.write_bytes(capture_bytes)
            snapshot["syntaxCapture"] = {
                "asset": capture.name, "version": args.syntax_version, "build": args.syntax_build,
                "sha256": hashlib.sha256(capture_bytes).hexdigest(),
            }
        write_json(assets / "snapshot.json", snapshot)
        shutil.move(str(mirror), str(output / "docs"))
    pack(output / "docs", assets / "snapshot.json", assets)
    print(json.dumps({"sourceCommit": commit, "htmlPages": audit["htmlPages"], "assets": str(assets)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", default="4d/docs")
    parser.add_argument("--source-ref", default="gh-pages")
    parser.add_argument("--source-commit")
    parser.add_argument("--source-directory", type=Path, help="Reuse a published source snapshot; requires --source-commit")
    parser.add_argument("--public-origin", default="https://developer.4d.com")
    parser.add_argument("--base-path", default="/docs/")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--work-directory", type=Path)
    parser.add_argument("--serve-package", default="serve@14.2.7")
    parser.add_argument("--startup-timeout", type=int, default=120)
    parser.add_argument("--generator-commit", help="Defaults to the script repository's HEAD")
    parser.add_argument("--syntax-json", type=Path)
    parser.add_argument("--syntax-version")
    parser.add_argument("--syntax-build")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.source_repo):
        parser.error("--source-repo must be owner/repository")
    if not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)+", args.base_path):
        parser.error("--base-path must be a non-root path with leading and trailing slashes")
    origin = urllib.parse.urlsplit(args.public_origin)
    if origin.scheme not in ("https", "http") or not origin.netloc or origin.path or origin.query or origin.fragment:
        parser.error("--public-origin must be an HTTP(S) origin without a path")
    if args.source_directory and not args.source_commit:
        parser.error("--source-directory requires --source-commit")
    try:
        generate(args)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, urllib.error.URLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
