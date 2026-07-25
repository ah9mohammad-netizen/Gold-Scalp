# Gold day-trading automation research — decision memo

**Prepared:** 25 July 2026  
**Scope:** research and paper trading of `XAU-USDT`; not investment advice and not a promise of returns.

> **Non-negotiable conclusion:** an automated gold system is an execution and risk-control tool, not a high-profit machine. The CFTC specifically warns that claims of outsized or guaranteed automated-trading returns are a fraud red flag, and notes that no technology can consistently predict future market changes. [CFTC advisory](https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/AITradingBots.html) · [CFTC forex guidance](https://www.cftc.gov/LearnAndProtect/forexfrauds)

The goal should be a small, measured process: collect clean fills and signal data, prove that it remains positive *after* fees/slippage across unseen periods, then decide whether it deserves more capital. Starting with **100 USDT in paper mode** is appropriate for validating plumbing, not for inferring a durable trading edge.

---

## 1. Instrument and venue facts that affect the design

### XAU-USDT is not the same as every “gold chart”

- Bybit announced an `XAUUSDT` perpetual listing on 9 March 2026, with leverage **up to** 75×. “Up to” is a venue limit, not a recommended operating leverage. [Bybit announcement](https://announcements.bybit.com/en/article/new-listing-xauusdt-perpetual-contract-with-up-to-75x-leverage-blt7475343901d47b34/)
- OKX renamed `XAUTUSDT` perpetual to `XAUUSDT` on 15 January 2026 and specifically told API users to move from `XAUT-USDT-SWAP` to `XAU-USDT-SWAP`. [OKX notice](https://www.okx.com/en-ae/help/okx-will-rename-xautusdt-perpetual-to-xauusdt-perpetual)
- `PAXG/USDT`, a CFD-based `XAU/USD` quote, COMEX futures, and an `XAU-USDT` perpetual can be correlated yet have different contract multipliers, mark/index construction, trading hours, funding, fees, liquidity, liquidation rules, and spreads. A bot must calculate risk on the **execution contract**, not on a proxy chart.

**Project decision:** the feed now prefers direct Bybit/OKX XAU instruments. A PAXG fallback is disabled by default (`ALLOW_PROXY_FEEDS=false`) and is conspicuously labelled if deliberately enabled. The bot calculates a signal only on a **closed** 5-minute candle, not a still-changing candle.

### Gold is schedule- and information-sensitive

Intraday research finds that the New York/London (“Nylon”) period is highly informative for gold price discovery and that US news surprises materially change the relationship; the reported US information share is 56% across the studied windows. [Study summary](https://www.sciencedirect.com/science/article/abs/pii/S1057521921002209)  Research on intraday jumps also identifies macro news, illiquidity, wider spreads, volatility, and order imbalance as relevant around gold jumps. [EFMA paper](http://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2024-Lisbon/papers/EFMA_COMPLETEMANU_NSOBTI.pdf)

That supports **filters** (session, spread, volatility, and news), but does *not* prove that a particular EMA, liquidity-sweep, or AI entry rule will profit. It is a reason to avoid treating every 24/7 crypto-perp candle as equivalent to institutional gold liquidity.

---

## 2. Automated-strategy landscape

| Family | Mechanism | Where it can make sense | Principal failure mode | Verdict for this bot |
|---|---|---|---|---|
| **Range mean reversion** | Fade an unusually large standardized deviation once a turn bar confirms and trend strength is low. | Quiet, two-sided, liquid regimes. | A range becomes a macro trend; short lookbacks overfit. | **Primary candidate.** Current v5 uses a Z-score, ADX, turn-bar, session, cost, and ATR gate. |
| **Session VWAP reversion** | Trade a rejection from a large distance to session VWAP, often with a volume/volatility gate. | Intraday rotational markets. | VWAP is dragged by a trend; no-news assumption breaks. | **Secondary research candidate**; needs a volume source representative of the execution venue. |
| **Trend pullback** | Join a strong directional move after a controlled pullback to VWAP/EMA/swing level. | Persistent post-news or macro trend. | False trend classification; repeated whipsaws/costs. | Test only as a separately labelled regime, not alongside a mean-reversion signal. |
| **Opening-range / Donchian breakout** | Enter an expansion beyond a defined session range. | High relative volume plus confirmed trend. | Gold often probes a range then reverses; stop clustering causes poor fills. | Keep disabled unless walk-forward results survive friction. |
| **Liquidity sweep / structure fade** | Detect a prior high/low sweep, close back through the level, then enter on a confirmed change in structure. | Can encode discretionary price action in an auditable rule set. | Subjective labels, repainting/look-ahead, and news spikes. | Suitable for a research branch only; require deterministic definitions and every rejected/accepted setup in the DB. |
| **Cross-venue basis/funding arbitrage** | Hedge a meaningful, executable difference between XAU perp, tokenized gold, and/or futures. | Only with two funded venues, reliable inventory, known contract conversions and low latency. | “Spread” disappears after fees, funding, transfer, legging, and liquidation risk. | Not viable for a 100-USDT single-venue pilot; it is execution infrastructure, not a chart signal. |
| **Market making** | Quote both sides and manage inventory. | Professional liquidity access, low fees, fast order-book data. | Adverse selection on news; inventory gets run over. | Reject for this deployment. |
| **ML / reinforcement learning** | Classify regime or choose actions from many features. | Large clean tick-level sample, strict out-of-sample process, stable feature availability. | Leakage, non-stationarity, opaque risk, and false confidence. | Use only as an offline regime classifier after baseline rules are proven. Never allow it to bypass risk gates. |
| **Grid / martingale / recovery** | Average into adverse moves to harvest small mean-reverting gains. | Backtests can look smooth in short ranges. | One directional gold move can exhaust margin before reversal. | **Reject.** No averaging down, no martingale, no “recovery” logic. |

### Commercial bots and “AI” bots

Gold EAs/cBots commonly advertise trend, reversal, grid, hedge, or recovery modes. A product description is marketing, not independently verified expectancy. For example, cTrader listings can describe “smart recovery” or AI labels while also carrying their own risk disclaimers. That is not enough evidence to hand the system capital. Treat any vendor bot as an opaque hypothesis unless it offers raw, broker-verifiable fills, contract/fee assumptions, full drawdown history, and a reproducible out-of-sample test.

A custom, inspectable rule engine is preferable here because it makes the complete decision chain—**source candle → indicators → signal → reference price → filled price → exit reason → net PnL**—available in `history.db`.

---

## 3. Recommended layered decision process

The project should separate *market state* from *entry* and *execution*. That avoids combining mutually contradictory strategies on every candle.

### Layer A — tradeability / kill switches

No new position when any condition is true:

1. Direct XAU-USDT feed is unavailable, stale, or marked as a proxy.
2. Current spread is above the configured ceiling.
3. Candle volatility is below the minimum required to cover costs or is an abnormal multiple of its baseline.
4. A high-impact, scheduled USD release buffer is active (initially 30 minutes before/after; use a licensed/reliable calendar feed before automating this in production).
5. Daily realized loss, maximum trades/day, cooldown, or operator pause is active.
6. Existing position count or margin cap would be exceeded.

### Layer B — regime classifier

Use a transparent first version:

- **Range:** ADX at/below threshold; ATR normal relative to its 50-bar baseline.
- **Trend:** ADX elevated *and* price/volume structure aligned; not merely “above an EMA.”
- **Event/abnormal:** news window, spread expansion, or ATR shock.

A single bar may be “no regime,” which is a valid action. The bot must prefer being flat to creating a trade to satisfy a frequency target.

### Layer C — setup rules

For the current primary range setup:

1. A closed 5-minute candle is inside the permitted UTC session.
2. The standardized close distance from SMA(20) is at least ±2.2.
3. ADX is at most 18 and ATR/cost gates pass.
4. The candle turns back in the proposed direction (bullish after a negative stretch; bearish after a positive stretch).
5. Enter only once that candle has closed. A later candle—not the signal candle—can hit the recorded SL/TP in the paper ledger.

The existing repository research ranked this family above breakout variations on its supplied historical sample; that is a **starting hypothesis**, not statistical proof. The same document reports weak/negative full-sample results for versions tested, so it should remain paper-only until new walk-forward evidence says otherwise.

### Layer D — execution, risk, and exits

- Size from the exact stop distance: `quantity = cash risk / stop distance`.
- Constrain notional by `MARGIN_CAP_PCT`; leverage changes collateral use, **not** the dollar loss at the stop.
- Use a hard ATR-based stop and a fixed 2R target in the baseline. Do not move a stop to breakeven because a backtest “feels safe”; test that as a separate experiment.
- Paper fills are conservative: long entry at ask + slippage, short entry at bid − slippage; exits use the executable bid/ask range. If OHLC says both stop and target were possible, the model records the stop first.
- Record entry/exit taker fees plus fixed slippage. Never optimise with fees set to zero.

With a 100-USDT account, a 1% risk budget is roughly 1 USDT before costs. A 50× control is not a reason to increase that risk: a small price error, fee, gap, or liquidation-rule mismatch can dominate the account. Do not describe any configuration as “high profit.”

---

## 4. What the Railway paper service now records

`/data/history.db` is the single persistent asset. The service creates it on the Railway Volume and `/get_db` creates a consistent SQLite backup before Telegram uploads it (important because a live SQLite WAL file can hold recent committed writes).

| Table | Analysis fields |
|---|---|
| `signals` | closed-bar timestamp, direct feed source, strategy/setup, reference price, actual paper fill, SL/TP, size, ADX/Z-score/ATR/spread, layered reasons and status |
| `trades` | source/candle, reference and filled price, margin, entry/exit fees, gross PnL, **net** PnL, exit reason, timestamps |
| `account_history` | immutable initial 100-USDT deposit and every realized balance change |
| `bot_state` | pause state and last processed candle timestamp (restart idempotency) |

This supports later questions that screenshots cannot answer: “Did signal quality degrade?”, “Were losses clustered around a session?”, “Did cost erase gross expectancy?”, and “Did a feed/source change coincide with results?”

---

## 5. Paper-to-live research gates

Do **not** enable a live adapter because the balance happens to rise for a few weeks. Require all of the following first:

1. **Instrument reconciliation:** chart, feed, and proposed ApeX contract have matching units, tick size, multiplier, index/mark behavior, trading hours, and fee/funding schedule.
2. **Sufficient independent data:** a development period, a frozen validation period, and an unseen forward-paper period. Report sample count and confidence intervals—not only win rate.
3. **Net performance:** calculate on fees, bid/ask, adverse stop gaps, and slippage worse than the observed median. Include funding if positions can cross a funding timestamp.
4. **Robustness:** perturb lookback, Z threshold, stop multiple, target, and sessions. An edge that exists only at one exact parameter set is probably curve-fit.
5. **Risk evidence:** maximum drawdown, longest loss streak, gap stress, data outage behavior, daily kill-switch behavior, and a manual `/close_all` drill.
6. **Operational evidence:** restart recovery, Telegram authorization, backup download, no duplicate candle processing, and alerts matching the database.
7. **Smallest possible live test:** if all prior gates pass and it is legally appropriate, use isolated collateral and an amount that can be entirely lost. Live execution needs an independent code/security review.

### ApeX implementation note (later, deliberately not enabled)

ApeX’s current API guidance requires checking listed contract configuration, contract-specific step/tick sizes, and using a WebSocket order update to confirm an order status; a successful REST response alone is not a fill. Its RWA API documentation also requires an explicit RWA account flow and signed orders. [ApeX API introduction](https://api-docs.pro.apex.exchange/) · [ApeX order/WS best practice](https://api-docs.pro.apex.exchange/practice/index.html)

Before writing any ApeX executor, query the **actual** contract list and verify that `XAU-USDT` is listed and tradable for the account/region. The research did not find sufficient authoritative evidence to assume that a particular ApeX XAU market is available to every account. The current code intentionally refuses `PAPER_TRADING=false`; credentials in Railway must not create an accidental live trading path.

---

## 6. Main-branch historical re-run — current baseline did not pass

A reproducible run was performed on the five supplied main-branch 5-minute CSV parts (443,451 bars, 2019-09-06 through 2026-01-30; data revision `9229cd58ff171df61180c12e16fc35cc8b716343`). It applied the **current** paper model: closed-bar decisions, fixed $0.40 spread, $0.03 adverse slippage per fill, 0.04% taker fee per side, and stop-first handling of ambiguous OHLC bars.

| Window | Closed trades | Final realized balance | Net return | PF | Max realized DD |
|---|---:|---:|---:|---:|---:|
| Full sample | 44 | $86.12 | −13.88% | 0.65 | $16.54 |
| 2022–2023 | 1 | $101.73 | +1.73% | n/a | $0.00 |
| 2025-01 onward | 20 | $94.28 | −5.72% | 0.70 | $6.51 |

The 2022–2023 segment has one trade, so its positive number has no evidential value. The full and recent segments are negative. **This baseline therefore fails the go-live gate.** Keep it in paper research mode; do not interpret a previous favourable report or a short forward streak as sufficient contrary evidence.

See [`BACKTEST_MAIN_HISTORY_V5_COST_AWARE.md`](BACKTEST_MAIN_HISTORY_V5_COST_AWARE.md) for assumptions and the exact reproduction command in [`scripts/backtest_v5_csv.py`](scripts/backtest_v5_csv.py). The per-trade audit, failure taxonomy, and deliberately rejected walk-forward parameter search are in [`TRADE_FORENSICS_AND_OPTIMIZATION.md`](TRADE_FORENSICS_AND_OPTIMIZATION.md).

## 7. Practical next experiments, in priority order

1. Run the current closed-candle, cost-aware paper engine for enough signals; download `/get_db` regularly.
2. Build a notebook that groups net results by UTC hour, side, ADX bucket, Z-score bucket, spread bucket, feed source, and exit reason.
3. Add a reliable high-impact-event calendar **only as a no-entry filter**; retain its event IDs in the signal data.
4. Compare the baseline Z-score range system with a separately-versioned VWAP-reversion system. Allocate no combined capital until each has independent net results.
5. Only then explore a deterministic liquidity-sweep model with no repainting and an explicit cancellation rule.

The correct output of research can be “stay flat” or “do not deploy live.” That is a successful risk-control outcome.
