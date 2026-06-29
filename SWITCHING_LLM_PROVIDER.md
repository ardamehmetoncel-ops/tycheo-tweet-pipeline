# Switching LLM Provider

Supported providers: `xai` · `anthropic` · `openai` · `ollama`

The **single source of truth** for which provider is active:

```
config/settings.yaml  →  llm.provider
```

`src/config.py` reads `.env` for secrets and passes everything to
`src/llm/provider.py:get_provider()`, which instantiates the right class.

```
.env                   → API keys / Ollama host URL
config/settings.yaml   → provider name + model name
src/llm/provider.py    → XAIProvider, AnthropicProvider, OpenAIProvider, OllamaProvider
```

---

## xAI — Grok (recommended)

Grok uses the OpenAI-compatible API at `https://api.x.ai/v1`. No extra SDK needed —
the `openai` package (already in `requirements.txt`) handles it.

### 1. Get an API key

Sign up at [console.x.ai](https://console.x.ai), create a key. It starts with `xai-`.

### 2. Add the key to `.env`

```env
XAI_API_KEY=xai-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 3. Set provider and model in `config/settings.yaml`

```yaml
llm:
  provider: xai
  model: grok-3-fast      # see model table below
  candidates_per_run: 3
```

#### Grok model options

| Model | Speed | Quality | Notes |
|---|---|---|---|
| `grok-3` | Slower | Highest | Best tweet quality |
| `grok-3-fast` | Fast | High | Best cost/speed balance (recommended) |
| `grok-3-mini` | Very fast | Good | Cheapest |
| `grok-3-mini-fast` | Fastest | Moderate | For testing |

### 4. Verify

```bash
python run.py
```

---

## Anthropic — Claude

### 1. Get an API key

[console.anthropic.com](https://console.anthropic.com) → API Keys → Create Key.

### 2. Add to `.env`

```env
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 3. `config/settings.yaml`

```yaml
llm:
  provider: anthropic
  model: claude-sonnet-4-6
```

#### Claude model options

| Model | Notes |
|---|---|
| `claude-sonnet-4-6` | Best cost/quality balance |
| `claude-opus-4-8` | Highest quality, higher cost |
| `claude-haiku-4-5-20251001` | Fastest, cheapest |

---

## OpenAI

### 1. Get an API key

[platform.openai.com](https://platform.openai.com) → API keys → Create new secret key.

### 2. Add to `.env`

```env
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 3. `config/settings.yaml`

```yaml
llm:
  provider: openai
  model: gpt-4o
```

---

## Ollama — local models (no API key)

### 1. Install Ollama

Download from [ollama.com](https://ollama.com) and install.

### 2. Pull a model

```bash
ollama pull llama3.1:8b       # 8B — runs on most machines with 8 GB+ RAM
ollama pull qwen2.5:7b        # good instruction-following
```

### 3. Start the server

```bash
ollama serve
```

### 4. `config/settings.yaml`

```yaml
llm:
  provider: ollama
  model: llama3.1:8b          # must match ollama list exactly
```

No `.env` changes needed unless Ollama is on a non-default host:

```env
OLLAMA_HOST=http://192.168.1.50:11434
```

---

## Switching providers (day-to-day)

One line in `settings.yaml` is all it takes — the `.env` keys are already set
from first-time setup.

```yaml
# Switch to Grok
llm:
  provider: xai
  model: grok-3-fast

# Switch to Claude
llm:
  provider: anthropic
  model: claude-sonnet-4-6

# Switch to Ollama
llm:
  provider: ollama
  model: llama3.1:8b
```

---

## Quick reference

| What to change | File | Key |
|---|---|---|
| Active provider | `config/settings.yaml` | `llm.provider` |
| Model name | `config/settings.yaml` | `llm.model` |
| xAI API key | `.env` | `XAI_API_KEY` |
| Anthropic API key | `.env` | `ANTHROPIC_API_KEY` |
| OpenAI API key | `.env` | `OPENAI_API_KEY` |
| Ollama server URL | `.env` | `OLLAMA_HOST` (optional, default: `http://localhost:11434`) |

---

## Troubleshooting

**`RuntimeError: XAI_API_KEY not set`**
Add `XAI_API_KEY=xai-...` to `.env`. Make sure you're running from the
`tweet-engine/` directory.

**`RuntimeError: ANTHROPIC_API_KEY not set`**
Add `ANTHROPIC_API_KEY=sk-ant-...` to `.env`.

**`requests.exceptions.ConnectionError` (Ollama)**
`ollama serve` is not running. Start it in a separate terminal.

**`404` or model not found (Ollama)**
The `model` in `settings.yaml` doesn't match a pulled model. Run `ollama list`
and copy the exact name.

**`AuthenticationError` (xAI)**
Key is malformed or expired. Regenerate at [console.x.ai](https://console.x.ai).
