# Tweet Engine — Claude Context

## What this is

A Polymarket-based tweet generation engine. Fetches prediction market data + curated Twitter handles, runs them through persona-based prompts, and generates tweet drafts. Output is reviewed manually — no auto-posting.

Entry points:
- `python run.py` — start the Flask web UI at http://127.0.0.1:5000
- `python -m src.generate` — run a batch from the terminal
- `python -m src.ingestion.fetch_handles` — fetch/refresh tweet cache
- `python -m src.classify.classifier` — classify handles into tiers/tags

---

## LLM provider

Set in `config/settings.yaml` under `llm:`. Swap with one line:

```yaml
llm:
  provider: xai          # xai | anthropic | openai | ollama
  model: grok-3-fast
  candidates_per_run: 3
```

Keys live in `.env` (`XAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.). Provider code: `src/llm/provider.py`.

---

## Persona system

10 personas defined in `config/personas.yaml`. Each has:

| field | purpose |
|---|---|
| `id` | snake_case key used everywhere |
| `name` | display name in UI |
| `tags` | routing tags — determines which handles feed this persona |
| `temperature` | per-persona LLM temperature |
| `ignore_markets` | if `true`, persona gets NO market data — voice tweets only |
| `sentiment_reactive` | unused for now |

### Current roster

| id | name | tier | ignore_markets |
|---|---|---|---|
| `edge_printr` | The Quant | serious | — |
| `fade_the_chalk` | The Fade | middle | — |
| `tick_by_tick` | The News Reaction | serious | — |
| `smart_money_tale` | The Narrative | middle | — |
| `still_has_value` | The Degen | degen | — |
| `market_goblin` | The Goblin | degen | — |
| `size_is_hitting` | The Whale Watch | quant/news | — |
| `the_take` | The Take | middle | ✓ |
| `the_reply_guy` | The Reply Guy | degen | ✓ |
| `the_comedian` | The Comedian | degen | ✓ |

Tier colors in UI: serious = teal `#3fb6c9`, middle = amber `#e8a73c`, degen = pink `#ff5d8f`. Voice-only personas show a purple `voice only` chip.

---

## Generation pipeline (`src/generate.py`)

```
fetch_markets() → markets_for_persona() → build_system_prompt() + build_user_prompt() → llm.generate()
```

**Key constants:**
- `_MARKETS_PER_PERSONA = 5` — market window per persona
- `_CONTEXT_PER_SOURCE = 5` — tweets sampled per handle
- `_MAX_CONTEXT = 20` — max voice tweets for market personas
- `_MAX_CONTEXT_VOICE_ONLY = 40` — max voice tweets for `ignore_markets` personas
- `_FILTER_ZERO_MARKETS = {"edge_printr"}` — personas that skip 0%/100% markets

**`ignore_markets` flag behaviour:**
- Bypasses `markets_for_persona()` entirely — `persona_markets = []`
- Passes `voice_only=True` to `build_user_prompt()` → different VOICE REFERENCE copy, no market section, different final instruction
- Uses `_MAX_CONTEXT_VOICE_ONLY` tweet cap
- Each voice-only persona gets a deterministic seed (`persona_idx`) so their tweet samples don't overlap
- `build_system_prompt()` skips the NUMBER DISCIPLINE block for these personas

**`size_is_hitting`** always gets top-volume markets, no offset applied.

**Market diversity:** each persona gets a shifted window `(offset * 5) % len(ranked)` from the movement-sorted market list. Offset = persona index in the config list.

**Dropped tweets:** tweets over 280 chars are hard-dropped with a `[drop]` log. A single retry fires for exactly the dropped count.

**GLOBAL_BLOCK** (prepended to every system prompt): identity, BANNED list, OUTPUT rules. Market-specific rules are conditional ("when market data is present"). NUMBER DISCIPLINE block appended after for market personas only.

---

## Handle routing (`src/routing.py`)

Sources are classified into `tier` + `tags` by the LLM classifier. Routing logic:

- **Shared pool** (`general`, `news` tags) → feeds ALL personas as info (tone not stolen)
- **Voice match** (tags intersect persona tags) → feeds matching personas as voice (tone stolen)

Handle list: `config/sources.yaml` — 92 handles, alphabetically sorted.
Classification cache: `data/cache/source_classifications.json` — permanent (no TTL), only new handles classified on each run. To reclassify from scratch: delete the file.

To refresh everything:
```bash
rm -rf data/cache/tweets/
python -m src.ingestion.fetch_handles
rm data/cache/source_classifications.json
python -m src.classify.classifier
```

---

## Web UI (`src/web/`)

- `app.py` — Flask routes: `/` (index), `/run` (POST, triggers batch), `/handle` (POST, saves handle)
- `templates/index.html` — full custom dark UI, no Bootstrap
- Per-persona sliders (0–4) control how many tweets to generate per persona
- Slider = 0 dims the card and skips that persona (saves tokens)
- Previous batch results are preserved for skipped personas
- Generate button shows live count of active personas

---

## Caches (`data/cache/`)

| file/dir | TTL | notes |
|---|---|---|
| `tweets/<handle>.json` | 12h | per-handle tweet cache |
| `source_classifications.json` | permanent | delete to reclassify |
| `last_batch.json` | permanent | last UI batch run |
| `batches/<timestamp>.json` | permanent | full batch history |
| `polymarket_*.json` | varies | market data cache |

---

## Tweet source

Set in `config/settings.yaml` under `tweet_source:`. Currently `unofficial_x` (twitterapi.io). See `SWITCHING_TWEET_SOURCE.md` for other options.
