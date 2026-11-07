---
name: regenerate-static-docs
description: Regenerate the published 4D documentation as a complete offline snapshot, audit local links, and publish pinned GitHub Actions artifacts and immutable Release assets.
---

# Regenerate static documentation

## Scope and prerequisites

Use this skill for static-page regeneration and publishing in this repository.
It does not build the Docusaurus source, generate embeddings, assemble language
IR, or approve semantic extraction differences.

The scripts use Python 3.11+, Node.js/npm (`npx`), Wget, and curl; publication
also requires an authenticated `gh`. The hosted workflow provisions Python
and Node on Ubuntu. Local execution is supported on macOS and Linux.
`serve@14.2.7` is the reproducible default server package and can be overridden.
It is provisioned through `npx`, not installed globally.

Scripts live in `scripts/static_docs/`. Read their `AGENTS.md` when changing
them. This repository-specific skill is deliberately outside `skills/`,
which is the separately mirrored, reusable 4D artifact skillset.

## Generate locally

Choose a **new** output directory and a published repository/ref. Defaults
are `4d/docs`, `gh-pages`, `https://developer.4d.com`, and `/docs/`; all are
parameters, not assumptions about versions or dates.

```sh
python3 scripts/static_docs/regenerate.py \
  --source-repo "$SOURCE_REPO" \
  --source-ref "$SOURCE_REF" \
  --public-origin "$PUBLIC_ORIGIN" \
  --base-path "$BASE_PATH" \
  --output "$OUTPUT_DIRECTORY" \
  --generator-commit "$(git rev-parse HEAD)"
```

For an already-downloaded **published** site, supply `--source-directory`
and its exact `--source-commit`. The directory contains `index.html`,
language/version folders, and assets, not the Docusaurus source project.
The script copies it into temporary staging and never modifies it.

To bundle a syntax resource, also pass:

```sh
--syntax-json "$SYNTAX_JSON" \
--syntax-version "$SYNTAX_VERSION" \
--syntax-build "$SYNTAX_BUILD"
```

Use the resource from the matching installed 4D app. Read the app's
`Contents/Info.plist` to establish the actual build; never infer it from a
directory name. Keep a new versioned capture separate from captures backing
the existing assembled data. Hosted jobs can use only committed repository
files, not a local `/Applications` path.

## What generation guarantees

1. Resolve the source ref to a full SHA and download that immutable archive.
2. Serve the published site on a dynamically allocated loopback port.
3. Crawl using Wget with page requisites and converted links, restricted to
   the local site path so documentation examples are not crawled.
4. Crawl additional source HTML files unreachable through navigation.
   Duplicate `.html.html` exports are excluded.
5. Rewrite valid local targets to exact-case relative links. Leave missing
   upstream targets as public links and record them in `link-report.json`.
6. Check complete source-page coverage, relative page/media references, CSS
   dependencies, preserved version badges, and absence of the temporary origin.
7. Stop the temporary server, remove temporary downloaded source, package
   the snapshot, and compute asset SHA256 checksums.

A completed crawl may report upstream 404s. That is not permission to ignore
network errors, other HTTP errors, missing published pages, or missing local
assets: those stop generation and publication. Failed output/log directories
remain available for diagnosis; retry into a new directory.

## Output contract

| Output | Meaning |
|---|---|
| `OUTPUT/docs/` | Offline pages and their downloaded assets |
| `OUTPUT/assets/docs.zip` | Contains `docs/` and `snapshot.json` at the archive root |
| `OUTPUT/assets/snapshot.json` | Source SHA, generator SHA, site parameters, HTML count, actual page version labels, unresolved-path count, optional syntax provenance |
| `OUTPUT/assets/link-report.json` | Unresolved upstream paths and crawl 404 count |
| `OUTPUT/assets/SHA256SUMS` | Checksums for every other published asset |
| `OUTPUT/assets/syntaxEN.json` | Optional unmodified syntax resource; absent when no capture was provided |
| `OUTPUT/logs/` | Wget and temporary-server diagnostics |

An extraction consumer downloads assets from a specific release/run, verifies
`SHA256SUMS`, and extracts `docs.zip`. It passes the extracted `docs/` directory
to its existing `--docs-root` input and chooses an explicit version, or its
documented stable-version selector. It must not regenerate the mirror.

If a capture was bundled, use its recorded `version`/`build` and hash.
If no capture was bundled, select a separate versioned capture explicitly and
surface any mismatch. Do not silently combine the current beta pages with an
older syntax resource.

## Hosted publishing

`.github/workflows/regenerate-docs.yml` exposes the same site and capture
parameters through `workflow_dispatch`. It uploads:

- Actions artifact `static-docs-RUN_ID`, containing the publication assets.
- Versioned Release assets `docs.zip`, `snapshot.json`, `link-report.json`,
  `SHA256SUMS`, and the optional syntax capture.
- A separate diagnostic artifact, including on generation failure.

The default release tag is derived from the source SHA and Actions run ID.
Supply `release_tag` to choose a different unique tag. Existing release
content is never overwritten, and archives at or above GitHub's 2 GiB asset
limit are rejected. A successful local generation can be published with:

```sh
python3 scripts/static_docs/publish.py \
  --assets "$OUTPUT_DIRECTORY/assets" \
  --repository "$DESTINATION_REPO" \
  --target "$(git rev-parse HEAD)" \
  --tag "$RELEASE_TAG"
```

The target commit belongs to the destination repository; it is not the
upstream documentation SHA. The publisher verifies checksums first.

A newly added manual workflow must exist on the default branch before GitHub
allows dispatch. Do not merge automatically to bypass this. With user approval,
validate a new workflow through a narrowly restricted temporary feature-branch
push trigger, then remove it; otherwise report the registration prerequisite.

## Install or commit a generated mirror

Do not replace a user's dirty generated files in place. Verify the staged
output, retain the previous mirror as a backup, and replace only the intended
generated directories. If committing, include the snapshot provenance and
versioned syntax capture, exclude raw `server/` and logs, and preserve existing
assembled `out/` data. Release/Actions publication alone does not require
committing the generated HTML.

## Validation

```sh
python3 -m unittest discover -s scripts/static_docs/tests -v
```

For end-to-end validation, regenerate a complete pinned published snapshot
into a new staging directory and inspect its manifest and link report. Verify
archive layout and checksums before publishing. Do not validate merely that
the default page opens: every published page and local asset must resolve.
