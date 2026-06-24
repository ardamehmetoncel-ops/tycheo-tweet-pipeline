# Switching LLM Provider: Claude ↔ Ollama

This guide covers the exact files and steps to switch the tweet-engine between
Anthropic (Claude) and Ollama (local models). Both providers are already
implemented in `src/llm/provider.py` — no code changes are ever needed.

---

## How the provider system works

There are three supported providers: `anthropic`, `openai`, and `ollama`.

The **single source of truth** for which one is active is:

```
config/settings.yaml  →  llm.provider
```

`src/config.py` reads `.env` for secrets and passes everything to
`src/llm/provider.py:get_provider()`, which instantiates the right class.

```
.env                   → API keys / Ollama host URL
config/settings.yaml   → provider name + model name
src/llm/provider.py    → provider classes (AnthropicProvider, OllamaProvider…)
```

---

## First-time setup — Claude (Anthropic)

### 1. Install the Anthropic SDK

The SDK is already in `requirements.txt`. If you haven't installed dependencies yet:

```bash
cd tweet-engine
python -m venv .venv          # skip if .venv already exists
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get an API key

1. Go to [console.anthropic.com](https://console.anthropic.com) and sign in.
2. Navigate to **API Keys** in the left sidebar.
3. Click **Create Key**, give it a name (e.g. `tweet-engine`), and copy the key.
   You will only see it once — paste it somewhere safe first.

### 3. Add the key to `.env`

If `.env` doesn't exist yet, copy the example:

```bash
cp .env.example .env
```

Open `.env` and fill in the key:

```env
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Leave `OPENAI_API_KEY` blank and `OLLAMA_HOST` commented out.

### 4. Set the provider in `config/settings.yaml`

```yaml
llm:
  provider: anthropic
  model: claude-sonnet-4-6     # see model list below
  candidates_per_run: 3
  output_language: english
```

### 5. Verify it works

```bash
python run.py
```

A successful run prints candidate tweets per persona. If you see
`RuntimeError: ANTHROPIC_API_KEY not set`, the key is missing or `.env` wasn't
found — make sure you're running from the `tweet-engine/` directory.

#### Available Claude models (as of mid-2026)

| Model ID | Notes |
|---|---|
| `claude-sonnet-4-6` | Default. Best cost/quality balance. |
| `claude-opus-4-8` | Highest quality. More expensive. |
| `claude-haiku-4-5-20251001` | Fastest, cheapest. |

---

## First-time setup — Ollama (local models)

Ollama runs models entirely on your machine. No API key required.

### 1. Install Ollama

Download from [ollama.com](https://ollama.com) and install it.

Verify the installation:

```bash
ollama --version
```

### 2. Pull a model

Ollama needs a model downloaded before it can serve requests. Pull one that fits
your hardware:

```bash
# Good quality, runs on most machines with 8 GB+ RAM
ollama pull llama3.1:8b

# Higher quality, needs ~16 GB RAM
ollama pull llama3.1:70b

# Lightweight, for machines with 4–8 GB RAM
ollama pull mistral:7b

# Good for instruction-following (tweet writing)
ollama pull qwen2.5:7b
```

Check what you have pulled:

```bash
ollama list
```

### 3. Start the Ollama server

Ollama runs a local HTTP server on port `11434`. Start it:

```bash
ollama serve
```

Keep this terminal open (or run it as a background service — see step 3b below).

To verify the server is up:

```bash
curl http://localhost:11434/api/tags
```

You should get a JSON response listing your pulled models.

**3b — Run Ollama as a background service (optional, macOS)**

If you want Ollama to start automatically:

```bash
# After installing the Ollama.app, it registers itself as a launch agent.
# Just open Ollama.app once and it will run in the menu bar automatically.
```

Or start it manually in the background:

```bash
ollama serve &
```

### 4. Configure `.env`

Open `.env`. The `OLLAMA_HOST` line is commented out by default — uncomment it
only if you're running Ollama on a non-default port or a remote machine.

For the standard local setup (port 11434) you don't need to change anything:

```env
ANTHROPIC_API_KEY=
# OLLAMA_HOST=http://localhost:11434   ← leave commented; default is already 11434
```

If Ollama is on a different port or a remote host:

```env
OLLAMA_HOST=http://192.168.1.50:11434
```

### 5. Set the provider in `config/settings.yaml`

```yaml
llm:
  provider: ollama
  model: llama3.1:8b     # must match a model you've pulled (check: ollama list)
  candidates_per_run: 3
  output_language: english
```

The `model` value here must exactly match the name shown by `ollama list`.

### 6. No extra Python packages needed

The Ollama provider uses the `requests` library, which is already in
`requirements.txt`. Nothing extra to install.

### 7. Verify it works

Make sure `ollama serve` is running, then:

```bash
python run.py
```

If you see `requests.exceptions.ConnectionError`, the Ollama server is not
running. Start it with `ollama serve`.

---

## Switching providers (day-to-day)

This is a **two-line change** — one in `settings.yaml`, one in `.env` is
usually already set from first-time setup.

### Claude → Ollama

**`config/settings.yaml`:**

```yaml
llm:
  provider: ollama          # was: anthropic
  model: llama3.1:8b        # must match an ollama list entry
```

Then start the Ollama server if it isn't running:

```bash
ollama serve
```

### Ollama → Claude

**`config/settings.yaml`:**

```yaml
llm:
  provider: anthropic       # was: ollama
  model: claude-sonnet-4-6  # or any Claude model ID
```

Make sure `.env` has `ANTHROPIC_API_KEY` set. No other changes needed.

---

## Changing the model without switching provider

Edit only the `model` line in `settings.yaml`:

```yaml
llm:
  provider: anthropic        # unchanged
  model: claude-opus-4-8     # changed from claude-sonnet-4-6
```

For Ollama, you must have the model pulled before changing this:

```bash
ollama pull mistral:7b
# then update settings.yaml: model: mistral:7b
```

---

## Troubleshooting

### `RuntimeError: ANTHROPIC_API_KEY not set`

- `.env` file is missing — run `cp .env.example .env` and fill in the key.
- You're running from a directory other than `tweet-engine/` — `src/config.py`
  looks for `.env` relative to the project root.
- The key is there but has extra whitespace or quotes — check for
  `ANTHROPIC_API_KEY= sk-ant-...` (note the space) or
  `ANTHROPIC_API_KEY="sk-ant-..."` (quotes are not needed and break loading).

### `requests.exceptions.ConnectionError` (Ollama)

- Ollama server is not running. Start it: `ollama serve`.
- Wrong host in `.env`. The default is `http://localhost:11434`; check
  `OLLAMA_HOST` if you set a custom value.

### `404` or `model not found` error (Ollama)

- The `model` in `settings.yaml` doesn't match any pulled model.
- Run `ollama list` to see exact model names, then copy the name verbatim into
  `settings.yaml`.

### Slow responses (Ollama)

- The model is too large for your RAM and is being swapped to disk. Try a
  smaller model: `ollama pull llama3.2:3b` and set `model: llama3.2:3b`.

### Tweets sound generic / low quality (Ollama)

- Smaller local models produce lower-quality persona voice than Claude.
  Try `llama3.1:8b` or `qwen2.5:7b` before dropping to 3B-class models.
- Raise `candidates_per_run` in `settings.yaml` to generate more options to
  pick from, which partially compensates for lower per-sample quality.

---

## Quick reference

| What to change | File | Key |
|---|---|---|
| Active provider | `config/settings.yaml` | `llm.provider` |
| Model name | `config/settings.yaml` | `llm.model` |
| Anthropic API key | `.env` | `ANTHROPIC_API_KEY` |
| Ollama server URL | `.env` | `OLLAMA_HOST` (optional) |

**Supported `llm.provider` values:** `anthropic` · `openai` · `ollama`
