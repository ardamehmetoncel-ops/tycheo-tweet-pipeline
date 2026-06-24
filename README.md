# Tweet Draft Engine

A local tool that generates draft tweets for 10 prediction-market personas
(Polymarket-focused, with a global football angle). It produces candidates — you
review them in a local web UI, copy the ones you like, and post manually. No
auto-posting, no scheduling, no X write access.

---

## How it works

```
Polymarket (live odds + price movement) ──┐
                                          ├─> per-persona prompt ─> LLM ─> N candidates ─> web UI
source tweets ──> classifier ─────────────┘          ▲
(tier + topic tags, cached)                          │
                                         FinBERT sentiment (optional, 3 reactive personas)
```

For each persona the engine assembles:
- **Market context** — live Polymarket odds and recent price movement
- **Voice inspiration** — tweets from sources whose tags match the persona
- **Information context** — the shared news/general pool (tone ignored, facts used)
- **Sentiment signal** — FinBERT market-mood score for the 3 reactive personas

The LLM returns N candidate drafts per persona. You pick and post.

---

## Project layout

```
tweet-engine/
├── run.py                          # entrypoint → launches the web UI
├── requirements.txt                # base dependencies
├── requirements-finbert.txt        # optional: transformers + torch (sentiment layer)
├── .env.example                    # copy to .env and fill in keys
├── config/
│   ├── settings.yaml               # LLM provider, tweet source adapter, all toggles
│   ├── personas.yaml               # 10 personas: voice prompts, handles, source tags
│   ├── sources.yaml                # flat list of source handles (no tags)
│   └── handles.yaml                # auto-created: per-persona @handle edits from the UI
├── data/
│   ├── curated_tweets.yaml         # your example tweets per source handle (curated adapter)
│   └── cache/                      # market data, classifications, tweets, last-run batch
└── src/
    ├── config.py                   # load settings + .env; persist handle edits
    ├── cache.py                    # tiny JSON file cache with TTL
    ├── ingestion/
    │   ├── polymarket.py           # Gamma odds + CLOB price movement + snapshot diff
    │   ├── tweets.py               # TweetSource: curated + official_x + unofficial_x
    │   └── fetch_handles.py        # step 1: fetch + cache tweets for all source handles
    ├── classify/classifier.py      # step 2: LLM auto-classifier (reads tweet cache, no network)
    ├── routing.py                  # tag-based source → persona routing (voice / info split)
    ├── llm/provider.py             # anthropic / openai / ollama + N-candidate generation
    ├── generate.py                 # per-persona generation orchestration
    ├── sentiment/finbert.py        # optional FinBERT sentiment scoring
    └── web/
        ├── app.py                  # Flask UI: persona cards, copy button, handle editor
        └── templates/index.html
```

---

## Full setup and run — step by step

### Step 1 — Python environment

Navigate to the project root and create a virtual environment:

```bash
cd tweet-engine
python3 -m venv .venv
```

Activate it:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

You should see `(.venv)` in your prompt. Install the base dependencies:

```bash
pip install -r requirements.txt
```

---

### Step 2 — Create your `.env` file

Copy the example and fill in the keys for whatever LLM provider and tweet source
adapter you're using:

```bash
cp .env.example .env
```

Open `.env`. It looks like this:

```env
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
OLLAMA_HOST=http://localhost:11434

X_BEARER_TOKEN=
# TWITTERAPI_IO_KEY=
```

Fill in only what you need (see Step 3 and Step 4 below). Leave the rest blank.

---

### Step 3 — Choose and configure an LLM provider

Open `config/settings.yaml` and set `llm.provider` and `llm.model`:

```yaml
llm:
  provider: ollama          # anthropic | openai | ollama
  model: llama3.1:8b        # must match the provider (see table below)
  candidates_per_run: 3
  output_language: english
```

#### Option A — Ollama (local, no API cost)

1. Download and install Ollama from [ollama.com](https://ollama.com).
2. Pull the model you want to use:
   ```bash
   ollama pull llama3.1:8b
   ```
3. Start the Ollama server (keep this terminal open, or run it in background):
   ```bash
   ollama serve
   ```
4. In `.env`, `OLLAMA_HOST` is already set to `http://localhost:11434` — no change
   needed unless you're running Ollama on a different port or machine.
5. In `settings.yaml`: `provider: ollama`, `model: llama3.1:8b`

Verify Ollama is running:
```bash
curl http://localhost:11434/api/tags
```
You should get a JSON list of pulled models.

#### Option B — Anthropic (Claude)

1. Get an API key from [console.anthropic.com](https://console.anthropic.com) →
   **API Keys → Create Key**.
2. Add it to `.env`:
   ```env
   ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxx
   ```
3. In `settings.yaml`: `provider: anthropic`, `model: claude-sonnet-4-6`

| Model | Notes |
|---|---|
| `claude-sonnet-4-6` | Best cost/quality balance (recommended) |
| `claude-opus-4-8` | Highest quality, higher cost |
| `claude-haiku-4-5-20251001` | Fastest, cheapest |

#### Option C — OpenAI

1. Get an API key from [platform.openai.com](https://platform.openai.com) →
   **API keys → Create new secret key**.
2. Uncomment `openai` in `requirements.txt` and install it:
   ```bash
   pip install openai>=1.0
   ```
3. Add it to `.env`:
   ```env
   OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
4. In `settings.yaml`: `provider: openai`, `model: gpt-4o`

---

### Step 4 — Choose and configure a tweet source adapter

The tweet source provides voice inspiration for each persona. Open
`config/settings.yaml` and set `tweet_source.adapter`:

```yaml
tweet_source:
  adapter: unofficial_x     # curated | official_x | unofficial_x
  per_account_limit: 20
  cache_ttl_hours: 12
```

#### Option A — curated (no API key, recommended for first run)

You supply example tweets in `data/curated_tweets.yaml`. No network calls, no key
needed.

Add handles to `config/sources.yaml`:

```yaml
sources:
  - somequanthandle
  - somefootballhandle
  - somenewshandle
```

Add example tweets to `data/curated_tweets.yaml`:

```yaml
handles:
  somequanthandle:
    - "Implied 62% but my model says 71%. +9 edge. Taking yes."
    - "Vol spiked, price flat. Someone knows something the book doesn't."
  somefootballhandle:
    - "City title at 0.74 is rich. Draw-no-bet is real value."
  somenewshandle:
    - "BREAKING: rate decision moved the odds 8 points in minutes."
```

Aim for 5–10 tweets per handle. These are voice examples — they don't need to be
real tweets, just representative of how the account sounds.

#### Option B — unofficial_x (twitterapi.io, live tweets, no X approval)

> Violates X's Terms of Service. Use at your own risk.

1. Sign up at [twitterapi.io](https://twitterapi.io) and copy your API key from
   the dashboard.
2. Add it to `.env`:
   ```env
   TWITTERAPI_IO_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
3. In `settings.yaml`: `adapter: unofficial_x`
4. Add real X handles to `config/sources.yaml` — these are fetched live, no
   entries needed in `curated_tweets.yaml`.

#### Option C — official_x (X API v2, compliant)

1. Create an X Developer account at [developer.twitter.com](https://developer.twitter.com).
2. Create an app → **Keys and tokens → Bearer Token → Generate**.
3. Add it to `.env`:
   ```env
   X_BEARER_TOKEN=AAAAAAAAAAAAAAAAAAAAAxxxxxxxxxxxxxxxxxxxxx
   ```
4. In `settings.yaml`: `adapter: official_x`

> Requires at least the X API Basic tier ($100/month) for the timeline endpoint.

For a full guide on switching adapters, see `SWITCHING_TWEET_SOURCE.md`.

---

### Step 5 — Add your source handles

Edit `config/sources.yaml` with the X handles you want as inspiration sources.
These are the accounts the classifier reads to assign a tier and topic tags:

```yaml
sources:
  - handle1
  - handle2
  - handle3
```

- For `curated`: every handle listed here must also have entries in
  `data/curated_tweets.yaml`.
- For `official_x` / `unofficial_x`: handles are fetched live. No
  `curated_tweets.yaml` entries needed.

---

### Step 6 — Verify Polymarket connectivity (optional but recommended)

This checks that the Gamma and CLOB APIs are reachable and returning expected
data. It makes no LLM calls and costs nothing:

```bash
python -m src.ingestion.polymarket
```

You should see a list of markets with odds and price movement data printed to
the terminal. If you see errors, check your internet connection — no config
changes are needed for Polymarket (it's a public API).

---

### Step 7 — Fetch tweets and classify your sources

This is a two-step process. The fetch and classify steps are intentionally split
so that rate limits or API credit issues during fetching don't block the LLM
classification step.

**Step 7a — Fetch tweets (network only, no LLM)**

Downloads and caches recent tweets for every handle in `sources.yaml`. Safe to
re-run — handles already in cache are skipped automatically:

```bash
python -m src.ingestion.fetch_handles
```

Expected output:
```
[fetch] fetching 13 handle(s)...
[fetch] fetched (12): danielbkck, polymarket, kalshi, ...
[fetch] failed  (1):  somehandle
[fetch] re-run to retry failed handles
```

If any handles fail (rate limit, network error), run it again. Already-fetched
handles are skipped and the failed ones are retried. Repeat until all show as
"already cached".

**Step 7b — Classify from cache (LLM only, no network)**

Reads the cached tweets and runs one LLM call per unclassified handle to assign
a tier (`serious / middle / degen`) and topic tags. Results are saved to
`data/cache/source_classifications.json`:

```bash
python -m src.classify.classifier
```

Expected output:
```
[classifier] danielbkck          tier=degen     tags=['crypto', 'news']
[classifier] polymarket          tier=serious   tags=['general', 'news']
...
[classifier] 13 handle(s) classified
```

If any handles have no tweet cache yet (missed in step 7a), the classifier
prints a warning and skips them — run step 7a again to fetch those first.

**Adding new handles later:**

```bash
# 1. add handle to config/sources.yaml
# 2. fetch its tweets
python -m src.ingestion.fetch_handles
# 3. classify it (already-classified handles are skipped)
python -m src.classify.classifier
```

**Force a full reclassification:**

```bash
rm data/cache/source_classifications.json
python -m src.classify.classifier
```

---

### Step 8 — Start the app

```bash
python run.py
```

The terminal will print:
```
Draft Desk: 10 personas, N sources, provider=ollama
Open http://127.0.0.1:5000
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

---

### Step 9 — Using the UI

**Generate drafts**
Click the **Generate drafts** button. This runs the full pipeline:
Polymarket data → tweet source → routing → LLM → N candidates per persona.
It takes roughly one LLM call per persona (10 calls total). Progress is shown
in the terminal.

**Read and copy candidates**
Each persona card shows its N draft tweets. Click the copy button next to any
draft to copy it to your clipboard. Paste and post manually on X.

**Set persona handles**
Each card has an `@handle` field. Set it to the X account that persona posts
from. These are saved to `config/handles.yaml` and persist across restarts.

**Regenerate**
Hit **Generate drafts** again at any time to produce a fresh batch. The
previous batch is shown until a new one finishes.

---

## Optional — FinBERT sentiment layer

FinBERT adds a market-mood signal to the three reactive personas (The
Contrarian, The Hype Man, The News Reactor). It is heavy to install and not
needed for the first run.

**Install:**
```bash
pip install -r requirements-finbert.txt
```

This installs `transformers` and `torch` (~2 GB download for the model weights
on first use).

**Enable in `config/settings.yaml`:**
```yaml
finbert:
  enabled: true
  default_on_personas: [news_reactor, contrarian, hype_man]
```

**Disable:**
```yaml
finbert:
  enabled: false
```

---

## Configuration reference

All configuration lives in `config/settings.yaml`. Secrets (API keys) live in
`.env`. Never put secrets in `settings.yaml`.

### LLM

| Key | Values | Default |
|---|---|---|
| `llm.provider` | `anthropic` · `openai` · `ollama` | `anthropic` |
| `llm.model` | Model ID (provider-specific) | `claude-sonnet-4-6` |
| `llm.candidates_per_run` | Integer | `3` |
| `llm.output_language` | Any language name | `english` |

For a full guide on switching LLM providers, see `SWITCHING_LLM_PROVIDER.md`.

### Tweet source

| Key | Values | Default |
|---|---|---|
| `tweet_source.adapter` | `curated` · `official_x` · `unofficial_x` | `curated` |
| `tweet_source.per_account_limit` | Integer (max tweets fetched per handle) | `15` |
| `tweet_source.cache_ttl_hours` | Number (hours before re-fetching) | `24` |

### Classifier

| Key | Values |
|---|---|
| `classifier.tiers` | `[serious, middle, degen]` |
| `classifier.topic_tags` | `[quant, macro, football, news, general, crypto, politics]` |

### Secrets (`.env`)

| Key | Used when |
|---|---|
| `ANTHROPIC_API_KEY` | `llm.provider: anthropic` |
| `OPENAI_API_KEY` | `llm.provider: openai` |
| `OLLAMA_HOST` | `llm.provider: ollama` (default: `http://localhost:11434`) |
| `X_BEARER_TOKEN` | `tweet_source.adapter: official_x` |
| `TWITTERAPI_IO_KEY` | `tweet_source.adapter: unofficial_x` |

---

## The 10 personas

Spread across a serious → degen spectrum, each with its own voice and source tags:

| Persona | Tier | Tags | Sentiment reactive |
|---|---|---|---|
| The Quant | serious | quant, serious | |
| The Macro Narrator | serious | macro, serious | |
| The Sharp | serious | serious, news | |
| The Educator | middle | middle, quant | |
| The Arb Hunter | middle | middle, quant | |
| The Contrarian | middle | middle, news | ● |
| The Football Crossover | middle | football, middle | |
| The Hype Man | degen | degen, news | ● |
| The Memelord | degen | degen | |
| The News Reactor | degen | degen, news | ● |

Voices are defined by each persona's `system_prompt` in `config/personas.yaml`.
Persona `@handle` fields are blank by default — set them in the UI and they are
saved to `config/handles.yaml`.

---

## Compliance notes

- **Tweet source.** `curated` and `official_x` are compliant with X's ToS.
  `unofficial_x` (twitterapi.io) routes around the official API and violates
  X's ToS — use at your own risk.
- **Persona separation.** Ten accounts in one niche can trigger X's
  coordinated-inauthentic-behavior detection if they amplify each other. Keep
  the accounts genuinely independent. Talking up a market you hold a position
  in is sentiment manipulation on a real-money venue.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'anthropic'`**
Run `pip install -r requirements.txt` inside the activated `.venv`.

**`RuntimeError: ANTHROPIC_API_KEY not set`**
`.env` is missing or the key is blank. Run `cp .env.example .env` and fill in
the key. Make sure you're running commands from the `tweet-engine/` directory.

**`requests.exceptions.ConnectionError` (Ollama)**
`ollama serve` is not running. Start it in a separate terminal.

**`RuntimeError: TWITTERAPI_IO_KEY not set`**
Add `TWITTERAPI_IO_KEY=your_key` to `.env`.

**`ValueError: unknown tweet_source.adapter`**
The `adapter` value in `settings.yaml` doesn't match any of the three valid
options. Check for typos: `curated` · `official_x` · `unofficial_x`.

**Classifier produces empty tags for a handle**
The handle returned too few tweets (or none). For `curated`, add more example
tweets to `curated_tweets.yaml`. For live adapters, verify the handle is a
real, public, active X account.

**"Generate drafts" button returns an error**
Check the terminal running `run.py` — the full error and traceback are printed
there. Common causes: LLM API key missing/invalid, Ollama not running, no
classified sources.

**Port 5000 already in use**
Another process is on port 5000. Either stop it or change the port in `run.py`:
```python
app.run(host="127.0.0.1", port=5001, debug=False)
```
