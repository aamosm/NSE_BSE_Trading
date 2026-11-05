# AI explanations of a stock's card (optional)

The Stocks tab can ask a Claude model to explain one stock's research card in plain language: the maths step by
step with that stock's numbers, what the numbers mean together, what would change the call, general context and
what to check. It is optional. Everything else in MarketLab works without it, and it never changes a ranking or a
decision.

## Setting it up

1. Install the optional SDK in the environment that runs the web app: `pip install -e .[ai]` (or `pip install anthropic`).
2. Open **Controls & AI → AI explanations**. Paste an Anthropic API key (`sk-ant-…`) and choose where it is kept:
   - **This session only:** in the web server's memory, gone when it restarts.
   - **Private env file:** saved as `RESEARCH_PROVIDER=anthropic` and `RESEARCH_PROVIDER_KEY=…` in `data/private/.env`
     (git-ignored; the env loader's allow-list and forbidden-name checks still apply).
   The key is never shown again, never logged, never stored with an answer and never sent anywhere except Anthropic's API.
3. Set the spending caps (monthly, daily, per ask, asks per day). The monthly cap can never exceed the hard ceiling in
   `researcher/budget.py` (US$10).
4. Open a stock in the Stocks tab, choose a question (or type one) and press **Ask**.

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

- **API call:** `client.messages.stream(...)` with adaptive thinking and `output_config.effort` (low, medium or high).
  The system prompt is a cached block. Opus and Sonnet use `client.beta.messages.stream(..., betas=["server-side-fallback-2026-07-01"], fallbacks="default")`,
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
