# Tweet Source: Setup & Switching Guide

Three adapters are available. One line in `config/settings.yaml` controls which
one is active:

```yaml
tweet_source:
  adapter: curated        # curated | official_x | unofficial_x
```

| Adapter | Source | Key required | X ToS |
|---|---|---|---|
| `curated` | `data/curated_tweets.yaml` (you write the tweets) | None | ✅ |
| `official_x` | X API v2, live tweets | `X_BEARER_TOKEN` | ✅ |
| `unofficial_x` | twitterapi.io, live tweets | `TWITTERAPI_IO_KEY` | ⚠️ violates X ToS |

---

## First-time setup

### curated

No API key. No network. You write example tweets and the classifier reads them.

**1. Add handles to `config/sources.yaml`**

```yaml
sources:
  - quantedge
  - footymarkets
  - bigmacronews
```

**2. Add example tweets to `data/curated_tweets.yaml`**

```yaml
handles:
  quantedge:
    - "Implied 62% but my model says 71%. +9 edge. Taking yes."
    - "Vol spiked, price flat. Someone knows something the book doesn't."
    - "Fading the crowd here. Sharp money is on no."

  footymarkets:
    - "City title at 0.74 is rich. Draw-no-bet is real value."
    - "Arsenal's xG over last 6 doesn't match a 0.18 title price."

  bigmacronews:
    - "BREAKING: Fed holds. Odds on rate cut moved 12 points in 3 minutes."
    - "CPI print above consensus. Inflation markets now pricing Jun cut at 38%."
```

Aim for 5–10 tweets per handle. These are voice examples — they don't need to be
real tweets, just representative of how the account sounds. The classifier uses
them to assign each handle a tier (`serious/middle/degen`) and topic tags.

**3. Set the adapter**

```yaml
# config/settings.yaml
tweet_source:
  adapter: curated
  per_account_limit: 15
  cache_ttl_hours: 24
```

**4. Classify and run**

```bash
python -m src.classify.classifier   # caches results in data/cache/source_classifications.json
python run.py
```

---

### official_x

Fetches real recent tweets from the X API v2. Results are cached per-handle to
avoid burning rate limits on every run.

**1. Create an X Developer account**

1. Go to [developer.twitter.com](https://developer.twitter.com) → **Sign up for free**.
2. Log in with the X account you want to use as the developer account.
3. Fill in the use case and app description fields and submit.

**2. Create an app and get a bearer token**

1. In the Developer Portal: **Projects & Apps → Overview → + Add App**.
2. Name the app (e.g. `tweet-engine`) and save.
3. Open **Keys and tokens → Bearer Token → Generate**.
4. Copy the token immediately (shown once):
   ```
   AAAAAAAAAAAAAAAAAAAAAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

**3. Understand the rate limits**

| Tier | Tweet reads / month | Cost |
|---|---|---|
| Free | 1 000 | $0 |
| Basic | 10 000 | $100/mo |
| Pro | 1 000 000 | $5 000/mo |

With 10 handles at 15 tweets each, one uncached run reads up to 150 tweets.
The `cache_ttl_hours` setting keeps most runs free of API calls.

> The `/2/users/:id/tweets` endpoint requires at least the **Basic** tier.
> The Free tier will return `403 Forbidden` for this endpoint.

**4. Add the token to `.env`**

```env
X_BEARER_TOKEN=AAAAAAAAAAAAAAAAAAAAAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**5. Set the adapter**

```yaml
# config/settings.yaml
tweet_source:
  adapter: official_x
  per_account_limit: 15     # v2 API: min 5, max 100 per request
  cache_ttl_hours: 24
```

**6. Add handles to `config/sources.yaml`**

```yaml
sources:
  - quantedge
  - footymarkets
  - bigmacronews
```

No entries needed in `curated_tweets.yaml` — the adapter fetches live tweets.
Retweets and replies are automatically excluded.

**7. Classify and run**

```bash
python -m src.classify.classifier
python run.py
```

**Force-refresh the tweet cache for one handle:**

```bash
rm data/cache/tweets/quantedge.json
```

**Wipe all tweet caches:**

```bash
rm data/cache/tweets/*.json
```

---

### unofficial_x

Uses [twitterapi.io](https://twitterapi.io) — a third-party proxy that returns
real tweet data without requiring an X Developer account.

> **ToS warning:** This violates X's Terms of Service. Use at your own risk.

**1. Create a twitterapi.io account**

1. Go to [twitterapi.io](https://twitterapi.io) → **Sign Up**.
2. Verify your email.
3. Go to the **Dashboard** and copy your API key.

**2. Add the key to `.env`**

```env
TWITTERAPI_IO_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**3. Set the adapter**

```yaml
# config/settings.yaml
tweet_source:
  adapter: unofficial_x
  per_account_limit: 20
  cache_ttl_hours: 12
```

**4. Add handles to `config/sources.yaml`**

```yaml
sources:
  - quantedge
  - footymarkets
  - bigmacronews
```

**5. Classify and run**

```bash
python -m src.classify.classifier
python run.py
```

---

## Switching between adapters

Once an adapter is set up (key in `.env`, handles in `sources.yaml`), switching
is a single line change in `config/settings.yaml`:

```yaml
tweet_source:
  adapter: unofficial_x   # ← change to: curated | official_x | unofficial_x
```

Restart `run.py` after changing it.

### What carries over between switches

| | curated | official_x | unofficial_x |
|---|---|---|---|
| `sources.yaml` handles | ✅ same list | ✅ same list | ✅ same list |
| Tweet cache | — (no cache) | ✅ reused | ✅ reused |
| Classifier output | ✅ reused | ✅ reused | ✅ reused |

### When to re-run the classifier after switching

The classifier cache (`data/cache/source_classifications.json`) is valid across
adapter switches. You only need to re-run it if:

- You switch **from `curated` to a live adapter** and the real account's voice
  differs noticeably from the examples you wrote.
- An account has changed its posting style since the last classification.

```bash
rm data/cache/source_classifications.json
python -m src.classify.classifier
```

---

## Troubleshooting

### curated

| Problem | Fix |
|---|---|
| Empty results in the classifier for a handle | Add at least 3 example tweets for it in `curated_tweets.yaml`, then re-run the classifier. |
| Edited `curated_tweets.yaml` but nothing changed | `CuratedSource` caches the file in memory. Restart `run.py`. |

### official_x

| Problem | Fix |
|---|---|
| `RuntimeError: X_BEARER_TOKEN not set` | `.env` is missing or the key is blank. Check it exists in the project root. |
| `403 Forbidden` | Your X API tier is Free. The timeline endpoint needs at least Basic ($100/mo). |
| `429 Too Many Requests` | Monthly quota hit. Increase `cache_ttl_hours`, reduce `per_account_limit`, or upgrade your tier. |
| `404` for a specific handle | Account doesn't exist or is private. Remove it from `sources.yaml`. |

### unofficial_x

| Problem | Fix |
|---|---|
| `RuntimeError: TWITTERAPI_IO_KEY not set` | Add `TWITTERAPI_IO_KEY=` to `.env`. |
| `401 Unauthorized` | Key is wrong or revoked. Regenerate it in the twitterapi.io dashboard. |
| `429 Too Many Requests` | Monthly quota hit. Increase `cache_ttl_hours` or upgrade your plan. |
| Empty tweet list for a handle | Account is private, suspended, or doesn't exist. Verify at `x.com/<handle>`. |
| Unexpected JSON shape | Add `print(r.json())` temporarily inside `UnofficialXSource.fetch()` to inspect the live response, then adjust field names (`t.get("text")`, `t.get("id")`, `t.get("createdAt")`) to match. |

---

## Quick reference

| Setting | File | Key |
|---|---|---|
| Active adapter | `config/settings.yaml` | `tweet_source.adapter` |
| Tweets fetched per handle | `config/settings.yaml` | `tweet_source.per_account_limit` |
| Cache duration | `config/settings.yaml` | `tweet_source.cache_ttl_hours` |
| Handle list | `config/sources.yaml` | `sources:` |
| Curated example tweets | `data/curated_tweets.yaml` | `handles:` |
| X API bearer token | `.env` | `X_BEARER_TOKEN` |
| twitterapi.io key | `.env` | `TWITTERAPI_IO_KEY` |
