# FinBERT Sentiment Layer — Setup Guide

FinBERT is an optional sentiment scoring layer. It reads recent tweets from
the shared news/general sources, scores their collective market mood, and passes
a **bullish / neutral / bearish** signal into the prompt for three reactive
personas:

| Persona | Effect |
|---|---|
| The Contrarian | Receives the mood signal and fades it |
| The Hype Man | Rides the momentum of the signal |
| The News Reactor | Frames breaking news in the context of the mood |

The other seven personas are unaffected by FinBERT.

Without FinBERT installed, those three personas still generate — they just don't
receive the sentiment context, so their output is less reactive to market mood.

---

## What FinBERT is

FinBERT is a BERT model fine-tuned on financial text
([ProsusAI/finbert](https://huggingface.co/ProsusAI/finbert)). It classifies
text as **positive**, **negative**, or **neutral** with confidence scores.

This pipeline uses it as a **scorer, not a generator** — it never writes text.
It reads the news-tagged source tweets, computes
`mean(P(positive) − P(negative))` across them, and maps that to a signal in
`[-1, 1]`. The LLM then uses that signal as context.

```
news/general source tweets
        ↓
   FinBERT scores each tweet
        ↓
   mean signal in [-1, 1]
        ↓
   label: bullish (>0.15) | neutral | bearish (<-0.15)
        ↓
   injected into prompt for Contrarian, Hype Man, News Reactor
```

---

## Hardware requirements

FinBERT runs on CPU — no GPU required. However:

| Hardware | Inference speed | RAM needed |
|---|---|---|
| Apple Silicon (M1/M2/M3/M4) | Fast (~1–3s) | ~500 MB |
| Intel Mac / PC CPU | Slower (~5–15s) | ~500 MB |
| NVIDIA GPU (CUDA) | Very fast (<1s) | ~500 MB VRAM |

The model weights are ~440 MB and are downloaded once on first use, then cached
locally by HuggingFace (`~/.cache/huggingface/`).

---

## Installation

FinBERT deps are kept separate from the base `requirements.txt` because
`torch` is large (~2 GB download). Install them only when you want the sentiment
layer:

**Step 1 — Activate your virtual environment**

```bash
source .venv/bin/activate     # macOS / Linux
# .venv\Scripts\activate      # Windows
```

**Step 2 — Install**

```bash
pip install -r requirements-finbert.txt
```

This installs `transformers>=4.40` and `torch>=2.2`. The download is ~2 GB
(mostly PyTorch). It may take several minutes depending on your connection.

**Step 3 — Verify the install**

```bash
python -c "from transformers import pipeline; print('OK')"
```

You should see `OK`. If you see an import error, re-run step 2.

**Step 4 — First run (model download)**

The model weights (~440 MB) are not included in the package — they download
automatically from HuggingFace on first use. You can trigger this manually
before running the full app:

```bash
python -c "
from transformers import pipeline
print('Downloading ProsusAI/finbert...')
pipeline('text-classification', model='ProsusAI/finbert', top_k=None)
print('Done. Model cached.')
"
```

This may take a minute or two on the first run. Subsequent runs load from
`~/.cache/huggingface/hub/` instantly.

---

## Enabling FinBERT

Open `config/settings.yaml` and make sure this block looks like this:

```yaml
finbert:
  enabled: true
  default_on_personas: [news_reactor, contrarian, hype_man]
```

`enabled: true` is the only switch needed. The `default_on_personas` list is
informational — it matches the three personas that have `sentiment_reactive: true`
in `personas.yaml` and is not read at runtime.

FinBERT runs automatically on every `Generate drafts` call when enabled. No
other changes are needed.

---

## Disabling FinBERT

Set `enabled: false` in `config/settings.yaml`:

```yaml
finbert:
  enabled: false
```

The three reactive personas will still generate — they just won't receive the
sentiment signal. `transformers` and `torch` do not need to be uninstalled.

---

## How the signal is used in generation

When FinBERT is enabled, `generate.py` calls `compute_sentiment()` once per
`Generate drafts` run. It:

1. Collects tweets from sources tagged `general` or `news` (the `shared_tags`)
2. Adds short natural-language summaries of any Polymarket markets that moved
   more than 3 points since the last run
3. Runs all those texts through FinBERT and averages the scores
4. Passes the result into the prompt for the three reactive personas

The signal injected into the prompt looks like:

```
MARKET MOOD (sentiment signal): bearish (-0.31)
```

The persona's system prompt then shapes how it reacts to that signal —
The Contrarian fades it, The Hype Man amplifies it, The News Reactor reports it.

---

## Confirming it's working

After enabling and installing, run the app:

```bash
python run.py
```

In the terminal, you should **not** see this warning:

```
[finbert] enabled but transformers/torch not installed — run: pip install -r requirements-finbert.txt. Skipping sentiment.
```

In the UI, the Contrarian, Hype Man, and News Reactor cards will show a
**SENTIMENT** badge next to their tier badge — confirming the signal is being
passed into their prompts.

---

## Troubleshooting

**`[finbert] enabled but transformers/torch not installed`**
FinBERT deps are not installed in the active venv. Run:
```bash
pip install -r requirements-finbert.txt
```

**`OSError: Can't load tokenizer for 'ProsusAI/finbert'`**
The model hasn't been downloaded yet or the download was interrupted. Re-run
the manual download command from Step 4.

**`ModuleNotFoundError: No module named 'torch'`**
The venv you activated is not the one where you installed the deps. Make sure
`(.venv)` is showing in your prompt before running any command.

**Slow first run after install**
Normal — the model is being downloaded and cached. Subsequent runs load from
local cache and are fast.

**FinBERT is slow on my machine**
FinBERT runs on CPU by default. On Intel Macs or older hardware it takes 5–15
seconds per generation run. This is a one-time cost per `Generate drafts` click
(the signal is computed once, not per persona). If it's too slow, set
`enabled: false` — the quality difference is small for most use cases.

**Signal always shows `neutral (0.00)`**
Your `general` and `news` tagged sources have no tweets in cache, so FinBERT
has nothing to score. Run `python -m src.ingestion.fetch_handles` to populate
the tweet cache, then re-generate.

---

## Uninstalling FinBERT deps

If you want to remove torch and transformers to free disk space:

```bash
pip uninstall torch transformers -y
```

The model cache can also be deleted:

```bash
rm -rf ~/.cache/huggingface/hub/models--ProsusAI--finbert
```

Set `enabled: false` in `settings.yaml` after uninstalling.
