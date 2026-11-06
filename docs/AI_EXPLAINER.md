# AI explanations of a stock's card (optional)

The Stocks tab can ask an Anthropic or Gemini model to explain one stock's research card in plain language: the maths step by
step with that stock's numbers, what the numbers mean together, what would change the call, general context and
what to check. It is optional. Everything else in MarketLab works without it, and it never changes a ranking or a
decision.

## Setting it up

1. For Anthropic, install the optional SDK: `pip install -e .[ai]`. Gemini uses Python's standard library and needs no SDK.
2. Set the provider and key in the private env file. For Gemini:

       RESEARCH_PROVIDER=gemini
       RESEARCH_PROVIDER_KEY=your_gemini_key

   For Anthropic, use `RESEARCH_PROVIDER=anthropic` and an Anthropic key. The key is never logged or returned.
3. Open **Controls & AI → AI explanations** to choose the provider and model, or to paste a key instead of editing
   the file:
   - **This session only:** in the web server's memory, gone when it restarts.
   - **Private env file:** saved as provider and `RESEARCH_PROVIDER_KEY=…` in `data/private/.env`
     (git-ignored; the env loader's allow-list and forbidden-name checks still apply).
     The key is never shown again, never logged, never stored with an answer and never sent anywhere except the
     selected provider's API.
4. Set the spending caps (monthly, daily, per ask, asks per day). The monthly cap can never exceed the hard ceiling in
   `researcher/budget.py` (US$10).
5. Open a stock in the Stocks tab, choose a question (or type one) and press **Ask**.

## Gemini (Google AI Studio key, free tier)

Verified 2026-11-06 against Google's pages and with a live call on the owner's key (`src/marketlab/gemini.py`):

- **Keys.** AI Studio keys created after 28 May 2026 are "auth keys" starting `AQ.`; the older `AIza…` keys are
  "standard keys". Both are sent in the `x-goog-api-key` header to
  `https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent`. The key never goes in a URL.
- **Models** (prices in `researcher/budget.py`, from https://aistudio.google.com/docs/pricing):

  | Model | Paid list price per 1M tokens (in / out, thinking included in out) | Notes |
  |---|---|---|
  | `gemini-3.8-flash` | $0.75 / $3.75 | Default and most capable. Free-tier projects are served last: it answers HTTP 503 "high demand" for long stretches. |
  | `gemini-3.6-flash` | $0.75 / $3.75 | |
  | `gemini-3.5-flash-lite` | $0.30 / $2.50 | First fallback; answered when 3.8 was busy. |
  | `gemini-3.1-flash-lite` | $0.25 / $1.50 | Second fallback, cheapest. |

- **Fallback.** With fallback on (the default), a busy model (503) moves straight to the next one; a quota error
  (429 `RESOURCE_EXHAUSTED`) waits once if Google's retry delay is 20 s or less, else moves on; a bad key, a
  permission problem or a malformed request stops at once, because another model would fail the same way. The
  stored answer records every attempt and the model that actually answered.
- **Cost on the free tier is $0.** The ledger still records the list-price equivalent (about $0.02 for a full
  explanation on 3.8 Flash), so the caps keep bounding spend if billing is ever enabled on the Google project.
- **Privacy.** Google's pricing page states that free-tier content is used to improve its products. What is sent
  is one stock's public market data, MarketLab's computed numbers, the glossary and the configured paper policy:
  no account data, no holdings, no keys, no identifiers.
- **Rate limits** are per Google Cloud project, per minute and per day, and shown in AI Studio; they are not
  published as fixed numbers.
- **Speed.** A full explanation on 3.8 Flash at medium thinking took about two minutes in the live check; the
  browser polls, so the page stays usable.

## What the model receives

- **System prompt (the same for every stock, so it can be cached):** the rules below, MarketLab's glossary, what every
  feature measures, the exact rule for every class, and the pipeline description.
- **User message:** that one stock's card. This is the class and its reasons, the forecast and its uncertainty, every
  feature with its rank, coefficient and contribution, the costs at the whole-share quantity, both gates, the "what
  would change the call" analysis and the eligibility checks. It also carries MarketLab's own narrative and insight
  rules, the model and data status, and the policy's configured paper capital.
- **Nothing else.** It never receives account data, holdings, cash, the Kite session or anything from the private env
  file. A test checks that none of the env file's values appear in the prompt.

Rules the model is given:

- copy every number from the card and compute none of its own;
- explain the steps in order;
- say which numbers support the call and which contradict it;
- label general knowledge as such;
- say "unvalidated" unless the card says PROMOTED;
- never tell the owner to buy or sell;
- write for someone new to quantitative finance.

After the answer arrives, MarketLab lists every number in it that does not appear on the card. Rounding is allowed,
and small counts and years are ignored. Those numbers are the model's own and unverified.

## Cost control (enforced in code)

| Step | What happens |
|---|---|
| Before the call | The worst case is **reserved** in the research usage ledger. That is the system text at the cache-write price, the card at the input price and `max_tokens` of output. With fallback on, a full second attempt at the fallback model's rates is added. The call is refused if the reservation would break the per-ask, daily or monthly cap. Nothing is sent in that case. |
| After the call | The reservation is **settled** at the cost of every attempt's reported tokens (`usage.iterations`), at the verified prices. Unknown models are charged at the highest verified rate. |
| On errors | A 401, 403, 404, 429 or 400 is released, because those are not billed. A timeout, connection error or 5xx is charged at the full reservation, because the request may have run. |

Verified prices (USD per million tokens; source: platform.claude.com pricing page, checked 5 Nov 2026):

| Model | Input | 5-min cache write | Cache hit | Output |
|---|---|---|---|---|
| Claude Opus 5.5 (default) | 4.00 | 5.00 | 0.20 | 20.00 |
| Claude Sonnet 5.5 | 2.00 | 2.50 | 0.10 | 10.00 |
| Claude Haiku 5.5 (prompt ≤ 100K) | 0.10 | 0.125 | 0.01 | 0.50 |

Approximate cost of one detailed answer, from the context sizes measured on the real ranking:

| Model | Typical answer | Reserved per ask (6,000 output tokens, fallback on) |
|---|---|---|
| Opus 5.5 | US$0.05–0.10 | about US$0.40 |
| Sonnet 5.5 | US$0.02–0.04 | about US$0.20 |
| Haiku 5.5 | under US$0.01 | under US$0.01 |

The reservation is released and replaced by the actual cost as soon as the answer arrives. At the default caps
(US$0.50 a day, US$5 a month), Opus allows about two asks a day; raise the caps in Controls if you want more.

## Request details

- **API call:** Anthropic uses `client.messages.stream(...)` with adaptive thinking and `output_config.effort` (low, medium
  or high). Gemini uses its `generateContent` REST endpoint: `systemInstruction` holds the rules, the user content
  holds the card and the question, and `thinkingConfig.thinkingLevel` carries the effort on the models that document
  it. On Anthropic the system prompt is a cached block. Opus and Sonnet use `client.beta.messages.stream(..., betas=["server-side-fallback-2026-07-01"], fallbacks="default")`,
  so a refused request is retried server-side on Anthropic's recommended model. Haiku 5.5 has no server-side fallback.
- **Storage:** answers are stored write-once in `runs/ai/<id>.json`. Each record holds the question, the models
  requested and served, the reported usage per attempt, the cost and the SHA-256 of the prompt texts. It also carries
  the label "AI commentary: not a MarketLab calculation and never a decision input".
- **Asynchronous asks:** an ask runs in a background thread and the page polls for the result, so long thinking cannot
  time out the browser.

## Files

- `src/marketlab/ai_explain.py`: settings, key handling, prompt and context, reservation, the call, the number check,
  history.
- `src/marketlab/researcher/budget.py`: verified prices (`CLAUDE_PRICES`, `PRICE_SOURCE`), `token_cost_usd`, the
  append-only ledger and caps.
- `src/marketlab/explain.py`: the deterministic narrative, insights and glossary that both the page and the model read.
- `tests/test_ai_explain.py`: covers reservation and settlement, caps, errors, the key never echoed, a context free of
  env values, the number check, the HTTP flow and a stand-in client. No network call is made.
