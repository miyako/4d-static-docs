# 4d-static-docs

Tools for turning [developer.4d.com](https://developer.4d.com) into a fully offline, browsable copy of the docs, plus a local semantic-search (RAG) backend built from the same content.

Repo: https://github.com/miyako/4d-static-docs

## Objectives

1. **Static mirror** — generate a static HTML copy of the [4D docs GitHub Pages site](https://github.com/4d/docs) that can be browsed with no web server, i.e. by opening files directly from disk.
2. **Embeddings** — extract plain-text chunks (with a small overlap) from the mirrored HTML and generate vector embeddings for them, for 5 languages.
3. **MCP server** — serve those embeddings from a Docker container running an MCP (Model Context Protocol) server backed by ONNX Runtime and SQLite (`sqlite-vec`), so any MCP-capable client (including 4D or Claude) can query the docs semantically. This part lives in a companion repo, [`miyako/doc4d`](https://github.com/miyako/doc4d) — see Part 3 below.

## Sources

- Live site: https://developer.4d.com
- Doc source repo: https://github.com/4d/docs
- Generated HTML lives on the `gh-pages` branch: https://github.com/4d/docs/tree/gh-pages

## Repository contents

| File | Purpose |
|---|---|
| `dependencies.json` | 4D Component Manager manifest — declares the 4D component/plugin dependencies below. |
| `onStartup.4dm` | Database method. Configures and launches `llama-server` (via the `llama.cpp` component) at project startup, pointed at the embedding model. |
| `onExit.4dm` | Database method. Terminates the `llama-server` process on quit. |
| `import.4dm` | Extracts plain-text chunks (with overlap) from the mirrored HTML for one language, using the `Extract` plugin, and requests embeddings from the local `llama-server` via 4D AIKit's OpenAI-compatible client. |
| `en.4dm` / `es.4dm` / `fr.4dm` / `pt.4dm` / `ja.4dm` | Thin wrappers that call `import("en")`, `import("es")`, etc. — one entry point per language. |
| `export.4dm` | Exports all imported doc entities (`ds.Doc`) to a `data.jsonl` file on the Desktop: one JSON object per line with `url`, `text`, `embedding`, `language`, `version`. |
| `import.py` | Reads `data.jsonl` and loads it into a `sqlite-vec` virtual table (`doc.db`), ready to be shipped inside the Docker image. |

## Dependencies (4D side)

Installed automatically via the 4D **Component Manager** — see https://blog.4d.com/tag/component-manager/ for how the manager and `dependencies.json` work.

| Name | Source | Version |
|---|---|---|
| event | https://github.com/miyako/event | ^20.0.19 |
| tcp | https://github.com/miyako/tcp | ^20.0.10 |
| workers | https://github.com/miyako/workers | ^20.0.19 |
| llama.cpp | https://github.com/miyako/llama-cpp | ^20.5.12 |
| 4D AIKit | https://github.com/4d/4D-AIKit | 4d |

Also required, installed separately as a plugin (not via `dependencies.json`):

- **Extract** — https://github.com/miyako/4d-plugin-extract — used to pull plain text out of the mirrored HTML files.

> Note: `llama.cpp`/`llama-server` here is only used **offline**, inside the 4D project, to generate the dataset's embeddings (Part 2). It is not part of the query-time MCP server in Part 3, which uses a separate ONNX export of the same model instead.

---

## Part 0 — Install the prerequisite tools

You only need **Git**, **Node.js** (for `npx`), **Wget**, and **Python** (via **micromamba**). Docker is only needed for Part 3.

### macOS

```sh
# Homebrew, if you don't already have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install git node wget micromamba
```

### Windows

Use **winget** (built into Windows 10/11) from a terminal:

```powershell
winget install --id Git.Git -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id JernejSimoncic.Wget -e
winget install --id micromamba.micromamba -e
```

> If `wget` isn't picked up on `PATH` after install, close and reopen your terminal. Alternatively install it via `choco install wget` if you use Chocolatey.

No Linux-specific instructions are provided — use macOS or Windows as above.

---

## Part 1 — Create a static local copy of developer.4d.com

This is a two-stage process: first serve the already-built `gh-pages` HTML locally with a throwaway dev server, then use `wget` to mirror that local server to disk with all links rewritten to relative paths.

### 1.1 Clone and check out the built site

```sh
mkdir server
cd server
git clone https://github.com/4d/docs.git .
git fetch origin gh-pages
git checkout gh-pages
```

### 1.2 Serve it locally

```sh
npx serve ./
```

Open **http://localhost:3000/docs** in a browser and confirm the site loads and navigates correctly. Leave this running — you need it live for the next step.

### 1.3 Mirror it to disk with rewritten links

In a **second** terminal window:

```sh
mkdir mirror
cd mirror

wget --mirror \
     --convert-links \
     --adjust-extension \
     --page-requisites \
     --no-parent \
     --no-host-directories \
     http://localhost:3000/docs/
```

This downloads every page reachable from `/docs/` and rewrites internal links so the result opens directly from disk (`file://…`) with no server running.

> **Note:** `wget --convert-links` rewrites links only *after* the entire crawl finishes. If the crawl is interrupted, the files on disk at that point still contain absolute (`http://localhost:3000/...`) links — re-run the same command to let it complete and convert them.

You can now stop the `npx serve` process from step 1.2 — the `mirror/` folder is fully self-contained. Open `mirror/localhost:3000/docs/index.html` (or wherever `wget` placed it, depending on your `wget` version's directory layout) directly in a browser to confirm.

---

## Part 2 — Generate embeddings from the mirrored docs

### 2.1 Model

Embeddings are generated with **LiquidAI's `LFM2.5-Embedding-350M`** model (GGUF, `Q8_0` quantization), chosen because it performs well both on CPU and GPU — see https://www.liquid.ai/blog/lfm2-5-retrievers.

Download the model and place it at:

```
~/.GGUF/LiquidAI/LFM2.5-Embedding-350M-Q8_0.gguf
```

(`~/.GGUF` is created automatically the first time `onStartup.4dm` runs, but the model file itself must be downloaded and placed there manually first.)

### 2.2 llama-server launches automatically

When the 4D project (the one containing these methods) starts, `onStartup.4dm` runs and:

1. Writes a `models.ini` describing the embedding model (dimensions, pooling mode, context size) to `~/.GGUF/llama-8080/`.
2. Launches `llama-server` (from the `miyako/llama-cpp` component) on `http://127.0.0.1:8080`, configured for embeddings (`embeddings: true`), with GPU offload enabled if available (`n_gpu_layers: 99`).

When the project quits, `onExit.4dm` terminates that `llama-server` process.

You do not need to start `llama-server` manually — just open the 4D project after placing the model file, and it starts for you.

### 2.3 Extract text and request embeddings

`import.4dm` (invoked per-language via `en.4dm`, `es.4dm`, `fr.4dm`, `pt.4dm`, `ja.4dm`) does the following, for each of the **5 languages**:

1. Locates the matching language subfolder inside the `mirror/docs` folder produced in Part 1.
2. Uses the **Extract** plugin (https://github.com/miyako/4d-plugin-extract) to pull plain text out of each HTML file, splitting it into overlapping token chunks (overlap ratio `0.09`, chunk length sized to the model's context window).
3. Sends each chunk to the local `llama-server` (started in 2.2) via 4D AIKit's OpenAI-compatible client to get a 1024-dimension embedding.
4. Stores the resulting doc entities (`ds.Doc`) — text, URL, language, version, embedding — in the 4D data model.

Run each language's method (`en`, `es`, `fr`, `pt`, `ja`) from the Method Editor or Explorer once the mirror is in place and `llama-server` is running.

### 2.4 Export to JSONL

Run `export.4dm`. It writes every imported doc entity to:

```
~/Desktop/data.jsonl
```

— one JSON object per line, shaped as:

```json
{"url": "...", "text": "...", "embedding": [0.1, 0.2, ...], "language": "en", "version": "20"}
```

### 2.5 Convert JSONL to a SQLite vector database

Set up the Python environment once:

```sh
micromamba create -n rag python=3.12
micromamba activate rag
pip install sqlite-vec
```

Sanity-check that your Python's `sqlite3` can load extensions:

```sh
python -c "
import sqlite3
db = sqlite3.connect(':memory:')
db.enable_load_extension(True)
print('OK')
"
```

> On macOS, the system Python sometimes ships without extension-loading support. If the check above fails, use the Python provided by micromamba/conda instead of `/usr/bin/python3`.

Then convert:

```sh
cd path/to/data.jsonl
python import.py
```

`import.py` reads `data.jsonl`, packs each 1024-dim embedding into a little-endian `float32` blob, and loads everything into a `sqlite-vec` virtual table (`chunks`) inside `doc.db`, committing every 2000 rows. It prints a running row count and a 3-row sample at the end for a quick sanity check.

Move the resulting `doc.db` into your Docker build folder (see Part 3):

```sh
mv doc.db docker/data/doc.db
```

---

## Part 3 — Run the MCP server in Docker

This part is maintained as its own repository, **[`miyako/doc4d`](https://github.com/miyako/doc4d)**, since the server, its Docker image, and its deployment are independent of the 4D-side extraction/embedding pipeline in Parts 1–2. A live instance is running at `https://doc4d-production.up.railway.app`.

> **Architecture note:** the design described earlier in this doc (Docker image with `llama-cpp-python` and a GGUF model baked in) is **not** what `doc4d` actually ships. The real implementation loads a plain **ONNX** export of `LFM2.5-Embedding-350M` directly via `onnxruntime` + `tokenizers` — `llama.cpp`/`llama-server` is only used *offline*, in Part 2, to build the original dataset inside the 4D project. At query time there is no `llama.cpp` dependency at all.

### 3.1 What's in the `doc4d` repo

```
doc4d/
├── Dockerfile
├── entrypoint.sh          # downloads model + DB from Hugging Face, starts nginx, then server.py
├── nginx_conf.template    # reverse proxy: CORS + rate limiting, $PORT templated in at runtime
├── requirements.txt       # mcp[cli], sqlite-vec, onnxruntime, tokenizers
├── server.py              # MCP server: embeds queries, runs cosine search via sqlite-vec
└── LICENSE                # MIT
```

Unlike the `docker/data` + `docker/models` folder layout sketched earlier, **the image ships with no model or database baked in**. On container start, `entrypoint.sh` downloads both from Hugging Face:

- `models/LFM2.5-Embedding-350M/model.onnx` + `tokenizer.json` ← model repo [`keisuke-miyako/doc4d-2026-08-05`](https://huggingface.co/keisuke-miyako/doc4d-2026-08-05)
- `data/doc.db` ← dataset repo [`datasets/keisuke-miyako/doc4d-2026-08-05`](https://huggingface.co/datasets/keisuke-miyako/doc4d-2026-08-05)

This keeps the image small and lets the corpus (produced by Part 2's `import.py`) be updated by re-uploading to the Hugging Face dataset repo, with no image rebuild required — just re-run the container (or clear a mounted volume) to force a re-download.

So the bridge from Part 2 to Part 3 is: take the `doc.db` produced by `import.py`, upload it to your Hugging Face dataset repo (replacing the manual `mv doc.db docker/data/doc.db` step described earlier), and separately export/upload an ONNX version of the same `LFM2.5-Embedding-350M` model used in Part 2.

### 3.2 Install Docker

**macOS:**

```sh
brew install --cask docker      # Docker Desktop
open -a Docker
```

(If you prefer OrbStack as a lighter-weight Docker Desktop alternative on macOS: `brew install --cask orbstack && open -a OrbStack`.)

**Windows:**

```powershell
winget install --id Docker.DockerDesktop -e
```

Launch **Docker Desktop** from the Start menu and wait for it to report "Docker Desktop is running" before continuing. (Docker Desktop for Windows requires WSL2, which the installer will prompt you to enable if it isn't already.)

### 3.3 Build and run locally

```sh
git clone https://github.com/miyako/doc4d.git
cd doc4d
docker build -t doc4d .
docker run --rm -p 8080:80 -e PORT=80 doc4d
```

On first start, the container downloads the ONNX model and `doc.db` from Hugging Face (can take a minute or two depending on connection speed), then the MCP server listens on **http://localhost:8080**, proxied through `nginx` (CORS enabled, rate-limited to 5 req/s per IP with a burst of 10).

Point your MCP client at `http://localhost:8080` (streamable-http transport) to query the imported 4D documentation from within Claude, 4D, or any other MCP-compatible tool.

Without Docker, you can also run it directly:

```sh
pip install -r requirements.txt
./entrypoint.sh
```

(Requires `nginx` on your `PATH` for the proxy/CORS/rate-limiting layer; or point an MCP client straight at `127.0.0.1:7860` and skip nginx entirely.)

### 3.4 The `search` tool

The server exposes one MCP tool, `search(query, language, version, full_text, k)`, which:

1. Embeds the query with the prefix `"query: "`, using CLS-token pooling + L2 normalization to match how the corpus embeddings were built in Part 2.
2. Pulls `k * 20` nearest neighbors from `sqlite-vec` by cosine distance, then filters that candidate set down to the requested `language` (`en`/`fr`/`es`/`pt`/`ja`) and `version` (`18`/`20`/`21`/`21-R3`/`21-R4`), since the vector index itself isn't partitioned by those fields.
3. Returns up to `k` (capped at 50) `{url, similarity, text?}` results, ordered by similarity.

Because filtering happens after an over-fetch rather than natively in the index, a rare `language`/`version` combination can return fewer than `k` results even if more exist in the corpus.

### 3.5 Deploying (Railway or elsewhere)

The live demo deploys straight from the Dockerfile on [Railway](https://railway.com): create a project from the GitHub repo, and Railway builds the Dockerfile with no extra config. Railway injects `$PORT` at runtime, and `entrypoint.sh` templates it into the nginx config automatically (`envsubst '${PORT}'`) — no manual port setup needed. Attach a Railway volume at `/app/models` and `/app/data` if you want to skip re-downloading the model/DB on every restart.

The same image runs anywhere that can run a container and reach `huggingface.co` over HTTPS on first boot (falls back to port `80` if `$PORT` isn't set) — e.g. a bare Docker host or Oracle Cloud.

For the full breakdown of the `search` tool's parameters, the ONNX embedding assumptions, and deployment details, see the [`doc4d` README](https://github.com/miyako/doc4d/blob/main/README.md) directly.

---

## Full pipeline, start to finish

```sh
# 0. install tools (see Part 0)

# 1. static mirror
mkdir server && cd server
git clone https://github.com/4d/docs.git .
git fetch origin gh-pages && git checkout gh-pages
npx serve ./          # leave running, in this terminal

# --- new terminal ---
mkdir mirror && cd mirror
wget --mirror --convert-links --adjust-extension --page-requisites \
     --no-parent --no-host-directories http://localhost:3000/docs/

# 2. embeddings (inside the 4D project)
#    - place LFM2.5-Embedding-350M-Q8_0.gguf in ~/.GGUF/LiquidAI/
#    - open the project -> llama-server auto-starts (onStartup.4dm)
#    - run en / es / fr / pt / ja methods to import + embed each language
#    - run export.4dm -> ~/Desktop/data.jsonl

micromamba create -n rag python=3.12
micromamba activate rag
pip install sqlite-vec
python import.py                       # -> doc.db

# upload doc.db (and an ONNX export of the model) to your Hugging Face repos,
# e.g. keisuke-miyako/doc4d-2026-08-05, so the doc4d server can fetch them

# 3. MCP server (separate repo: github.com/miyako/doc4d)
git clone https://github.com/miyako/doc4d.git
cd doc4d
docker build -t doc4d .
docker run --rm -p 8080:80 -e PORT=80 doc4d
```

## Notes & caveats

- `wget --convert-links` only rewrites links once the crawl completes fully — an interrupted mirror will contain absolute `localhost:3000` links until re-run to completion.
- The embedding model's context window is 8192 tokens per the Liquid AI blog post, even though the Hugging Face `config.json` lists `max_position_embeddings: 128000` — the code here uses the conservative blog figure.
- `overlap_ratio` for text chunking is fixed at `0.09`; token budget per chunk is the model's max context minus the prefix length and 3 reserved tokens (BOS/CLS + safety margin).
- Only 5 languages are imported: `en`, `es`, `fr`, `ja`, `pt`. When importing `en`, the other four language subfolders are explicitly skipped to avoid double-importing shared paths.
- This project targets **macOS and Windows** only; no Linux-specific setup is documented.
- The query-time server (`doc4d`) and the offline dataset-generation pipeline (Parts 1–2, this repo) intentionally use two different runtimes for the same model — `llama.cpp` to build the dataset, ONNX Runtime to serve queries — so double-check any change to pooling/normalization is applied identically on both sides, or search results will silently drift from what the corpus was built with.
- `doc4d`'s Docker image does not bake in the model or `doc.db`; both are pulled from Hugging Face at container start, so the container needs outbound HTTPS access to `huggingface.co` on first boot.
