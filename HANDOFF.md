# Handoff — Voice-Only Market Contamination Fix

## Sorun
`ignore_markets: true` olan personalar (`the_take`, `the_reply_guy`, `the_comedian`) hala market dili üretiyor. "My cat just entered the same prediction market", "poly odds cratering", "Polymarket combo" gibi şeyler çıkıyor.

## Bu chatte yapılanlar
- `_MARKET_KEYWORDS` seti eklendi — voice-only context'e giren tweetlerden market keyword'leri filtrele (`src/generate.py`)
- `_VOICE_ONLY_BLOCK` system prompt kuralı eklendi — LLM'e "Polymarket/Kalshi isimlerini kullanma" dendi (`src/generate.py`)
- Voice-only seed time-varying yapıldı — her 30dk farklı tweetler örnekleniyor, "Choice Markets" gibi tekrarlayan tweetlerin önüne geçildi (`src/generate.py`)
- `market_goblin` için lowest-volume market seçimi eklendi — niche/absürd markete denk gelsin diye (`src/generate.py`)
- `edge_printr` prompt düzeltildi — rationale kaldırıldı, sadece call (`config/personas.yaml`)
- `tick_by_tick` prompt düzeltildi — aynı event'e birden fazla candidate yazma yasağı (`config/personas.yaml`)
- `smart_money_tale` prompt düzeltildi — NUMBERS bloğu eklendi, kelimeyle sayı yasağı (`config/personas.yaml`)

## Kalan sorun — kök çözüm yapılmadı

Filtreler kafi gelmiyor. Sebep iki katmanlı:

**1. Handle pool kirli:** `degen` handle'ların çoğu crypto/quant trader'lar (`0x_samir`, `aaalexhl`, `caronpolymarket` vb.). Voice-only personalar bunlardan voice tone çekiyor, LLM market dilini absorbe ediyor.

**2. GLOBAL_BLOCK market language içeriyor:** "When market data is present" gibi ifadeler LLM'e bu projenin market context'inde olduğunu söylüyor.

## Yapılacak fix

`src/generate.py`'a şunlar eklenmeli:

### 1. Voice-only için ayrı GLOBAL_BLOCK
```python
_GLOBAL_BLOCK_VOICE_ONLY = """
You are a real Twitter account with opinions. You take sides. You are not neutral, cautious, or an assistant.

BANNED (hard rules):
- Hashtags. NFA/DYOR disclaimers. Saying or implying you are an AI. Em-dashes.
- Emoji only where your persona's voice calls for it — not sprinkled in.
- Corporate or brand tone. Forced jokes.
- Any reference to prediction markets, betting platforms, odds, prices, trading positions, or market outcomes. Never name Polymarket, Kalshi, Manifold, or any similar platform. Never use betting or trading language ("edge", "fade", "priced in", "at X%", "volume", "flow").

OUTPUT:
- English only. 280 character hard limit.
- Each candidate covers a different topic.
- Output tweet text only. No labels, no intro, no surrounding quotes, no explanation.
""".strip()
```

### 2. build_system_prompt'ta voice_only dalı
```python
def build_system_prompt(persona: dict) -> str:
    if persona.get("ignore_markets"):
        return _GLOBAL_BLOCK_VOICE_ONLY + "\n\n---\n\n" + persona["system_prompt"].strip()
    block = GLOBAL_BLOCK + "\n\n" + _NUMBER_DISCIPLINE_BLOCK
    return block + "\n\n---\n\n" + persona["system_prompt"].strip()
```
> Not: mevcut `_VOICE_ONLY_BLOCK` bu yaklaşımla gereksiz kalıyor, silinebilir.

### 3. Voice-only handle pool'dan crypto/quant handle'ları dışla
`run_batch`'te `all_handles` build edildikten sonra, `voice_only=True` ise:
```python
_MARKET_HANDLE_TAGS = {"crypto", "quant"}

if voice_only:
    all_handles = [
        h for h in all_handles
        if not (_MARKET_HANDLE_TAGS & set(classifications.get(h, {}).get("tags", [])))
    ]
```

## Dosyalar
- `src/generate.py` — tüm pipeline logic
- `src/routing.py` — handle → persona routing
- `config/personas.yaml` — persona tanımları
- `config/sources.yaml` — handle listesi
- `data/cache/source_classifications.json` — handle tag'leri (permanent cache)
