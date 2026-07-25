# XAU 5-minute trade forensics and parameter optimisation

**Data:** five 5-minute CSV parts from `origin/main` at revision `9229cd58ff171df61180c12e16fc35cc8b716343`

**Baseline:** current paper model, 100 USDT, 1% risk/trade, 50× maximum margin setting, 07:00–17:00 UTC, Z ±2.2, ADX ≤18, turn confirmation, 2.5 ATR stop, 2R target.

**Execution assumption:** fixed $0.40 spread, $0.03 adverse slippage per fill, 0.04% taker fee per side.

> **Verdict:** the baseline has no demonstrated tradable edge. Before fees it was essentially flat (gross PnL **−$0.03**); fees of **$13.85** converted that into **−$13.88** over 44 closed trades. A different parameter combination selected on the development period also failed both unseen periods. The correct action is to keep paper-only and reject the attempted optimisation—not deploy a more aggressive setting.

---

## 1. Baseline forensic scorecard

| Metric | Result | Critical reading |
|---|---:|---|
| Full-sample trades | 44 | Small for claiming a durable intraday edge. |
| Winners / losers | 18 / 26 | 40.9% net win rate is below what this bounded 2R/stop model needs once costs and gap loss are included. |
| Gross PnL before fees | −$0.03 | The signal is not paying for risk even before execution costs. |
| Simulated fees | −$13.85 | Costs are the major accounting loss, but not the only problem. |
| Net PnL / final balance | −$13.88 / $86.12 | Reject. |
| Profit factor | 0.65 | Below 1.0. |
| Recent 2025+ PnL / PF | −$5.72 / 0.70 | The more relevant recent segment also fails. |
| Average winner / loser | +$1.44 / −$1.53 | Winners are capped; losers are enlarged by executable stop gaps and costs. |
| Stop losses with MAE >1.1R | 15 of 26 | OHLC adverse movement often extends beyond the nominal stop before the simulated executable exit. |
| Ambiguous SL-and-TP candles | 0 | The negative result is not caused by a stop-first ambiguity assumption in these 44 trades. |

Source report: [`BACKTEST_MAIN_HISTORY_V5_COST_AWARE.md`](BACKTEST_MAIN_HISTORY_V5_COST_AWARE.md).

---

## 2. Trade-by-trade audit and decision checklist

Every closed trade is listed in [`BACKTEST_MAIN_HISTORY_V5_TRADE_AUDIT.csv`](BACKTEST_MAIN_HISTORY_V5_TRADE_AUDIT.csv). It is not a summary: each row is a monitored decision record containing:

| Checklist field | Question it answers | How to use it |
|---|---|---|
| `opened_at`, `entry_hour_utc` | When did the decision occur? | Detect session/timezone clustering; do not assume the CSV clock is confirmed UTC. |
| `direction`, `zscore`, `adx`, `atr`, `atr_ratio`, `turn_confirmed` | Did the setup meet the entry hypothesis? | Compare accepted losers with winners; a pass only means rules were met, not that the rule was predictive. |
| `reference_price`, `entry_price`, `sl_distance`, `size_oz` | Did execution materially change the intended trade? | Quantify spread/slippage and dollar risk. |
| `bars_held`, `mfe_r`, `mfe_before_exit_r`, `mae_r` | Did price actually reverse before it stopped out? | `mfe_before_exit_r` excludes the exit candle’s unknown intrabar path. It is the safe field for BE/trailing hypotheses. |
| `stop_overshoot_r` | How far did adverse movement exceed 1R? | Separate ordinary stop-outs from gap/volatility exposure. |
| `ambiguous_ohlc_exit` | Did the same OHLC bar touch SL and TP? | The model applies stop-first if this is true; it is false for this baseline sample. |
| `diagnosis_tag` | What failed or succeeded? | See taxonomy below. |
| `gross_pnl_usd`, fees, `net_pnl_usd`, `balance_after` | Was gross movement enough after realistic friction? | Optimise on **net**, never on a gross-only equity curve. |

### Decision taxonomy applied to every baseline trade

| Audit tag | Count | Net PnL | Meaning / action |
|---|---:|---:|---|
| `TP_CONFIRMED_REVERSAL` | 18 | +$25.96 | The range reversion reached the capped target. Keep as the reference successful pattern. |
| `NO_REVERSAL` — MFE before exit <0.25R | 14 | −$20.14 | Price continued against the fade almost immediately. A breakeven/trailing change cannot repair these; the **entry/regime filter** is wrong. |
| `WEAK_REVERSAL` — 0.25–0.5R | 4 | −$5.83 | Some movement occurred, but not enough to cover cost/risk. Test a different entry confirmation only on development data. |
| `PARTIAL_REVERSAL` — 0.5–1R | 2 | −$2.74 | Could motivate an exit experiment, but the sample is too small to change production logic. |
| `GAVE_BACK_AFTER_1R` | 6 | −$11.13 | These are the only trades for which a breakeven hypothesis is mechanically plausible. They are not evidence that BE works overall. |

The decisive failure is **not** “the take profit is too far away.” Fourteen of 26 losing trades never reached even +0.25R before failure. Those losses need better *market-state avoidance*, not a closer target.

---

## 3. Where the baseline fails

### A. ADX ≤18 is not a sufficient range classifier

ADX is lagging. A new directional impulse can still print low ADX while a 20-bar Z-score signals an apparent “stretch.” The bot then fades continuation. This is consistent with the 14 `NO_REVERSAL` losses.

**Research criterion before considering a new entry:** augment, do not replace, ADX with a non-overlapping state test such as:

1. price is inside a stable longer-horizon range (e.g. 60-bar range percentile),
2. the 20-bar mean is not moving strongly in the opposite direction,
3. no abnormal range/volume/spread event is occurring, and
4. the entry is not within a scheduled high-impact USD-event buffer.

Each must be stored as a separate Boolean/reason in `signals`; otherwise it cannot be audited.

### B. The present turn bar is weak evidence

The current rule accepts a single colour change plus prior-close relation. It does not require a reclaim of a meaningful level, a second confirming close, or evidence that the impulse has stopped. This makes it vulnerable to one-bar pauses inside a continuation move.

**Do not blindly add confirmation:** a second bar can improve quality while worsening fill price and reducing reward. It must be tested as an independently versioned rule with the same costs.

### C. Costs and asymmetric exits matter

- Target exits are limited near the planned 2R distance.
- Stop exits can gap through the nominal stop; 15/26 baseline stop-outs had executable adverse excursion beyond 1.1R.
- Even if gross PnL had been exactly zero, the $13.85 simulated fee bill would still make the strategy unsuitable.

A smaller target may increase hit rate but cannot rescue the 14 no-reversal losses by itself. A wider stop reduces stop frequency only if it does not increase dollar-gap loss or delay a required regime exit.

### D. Hour patterns are hypotheses, not settings

The full sample’s 13:00 UTC bucket was +$7.25 on seven trades, while 07:00, 08:00, 11:00, 14:00, and 15:00 were negative. But the development period has only two 13:00 trades, so changing production hours based on this would be obvious data mining. Treat 13:00 UTC as a **monitor-only hypothesis** until a pre-registered forward sample is collected.

### E. The timestamp and venue may be mismatched

The CSV `Date` column contains no timezone and has no bid/ask/funding/contract metadata. The analysis assumed UTC and a direct XAU-USDT-like execution model. Before using time-of-day conclusions, identify the source timezone and validate the actual target venue’s mark/index, tick size, fee tier, spread distribution, funding, and market hours.

---

## 4. Step-by-step parameter test

The compact search was deliberately constrained and walk-forward tested:

1. **Development only:** 2019-09 to 2022-12. Rank requires at least eight trades; otherwise an undefined/infinite PF cannot win.
2. **Step 1:** vary Z threshold and ADX maximum.
3. **Step 2:** vary session window using the Step-1 development winner.
4. **Step 3:** vary stop multiplier, target R, and a falsifiable breakeven threshold.
5. Freeze the selected candidate. Evaluate it on 2023–2024 validation and 2025+ holdout **without changing it**.

Full candidate tables: [`V5_PARAMETER_RESEARCH.md`](V5_PARAMETER_RESEARCH.md). Reproduction tool: [`scripts/optimize_v5_parameters.py`](scripts/optimize_v5_parameters.py).

### What was selected—and why it is rejected

The best eligible development candidate was:

```text
Z 2.4 | ADX ≤20 | SL 3.0 ATR | TP 1.5R | 12:00–17:00 UTC | turn required | BE at 1R
```

It was still negative in development (−1.35%, PF 0.82). More importantly, after freezing it:

| Candidate | Window | Trades | Net return | PF | Decision |
|---|---|---:|---:|---:|---|
| Baseline | 2023–2024 validation | 9 | +5.31% | 2.13 | Too few trades; not confirmation. |
| Baseline | 2025+ holdout | 20 | −5.72% | 0.70 | Reject baseline. |
| Development-selected change | 2023–2024 validation | 8 | −9.53% | 0.10 | Reject change. |
| Development-selected change | 2025+ holdout | 5 | −1.86% | 0.55 | Reject change. |

This is exactly why optimisation must be chronological: the apparent improvement in the development data did not survive a later sample. **No tested parameter should replace the current paper baseline.**

---

## 5. Phase 2 result — added regime filters were also rejected

The next diagnosis phase held the v5 entry, exit, sizing, and cost model fixed and tested only close-known state filters designed to avoid continuation fades:

- directionally opposing 10-bar SMA20 slope;
- maximum signal-candle range relative to ATR;
- rejection close-location within the signal candle;
- close back inside the prior 20-bar range; and
- maximum relative tick-volume versus the prior 20 bars.

The development-selected filter was a maximum signal-bar range of 1.25 ATR. It was still negative in development (PF 0.31), then declined from the baseline's −5.72% 2025+ result to **−7.34%** (17 trades, PF 0.59). The other tested filters were negative, identical to baseline, or had too few trades to be evidence.

See [`V6_REGIME_FILTER_RESEARCH.md`](V6_REGIME_FILTER_RESEARCH.md) and [`V6_REGIME_FILTER_RESEARCH.csv`](V6_REGIME_FILTER_RESEARCH.csv) for all candidates. This rejects simple single-bar OHLC/tick-volume filters as a fix; no v6 setting is promoted.

## 6. Promotion checklist for any future strategy version

A proposed `v6` must answer every item in the database and report, not merely show an attractive equity curve.

### Data and execution gates

- [ ] Exact instrument, timezone, contract multiplier, market hours, bid/ask, fee tier, funding, tick/step size documented.
- [ ] All inputs come from closed, non-stale bars; source changes are stored.
- [ ] Signal entry, actual fill, SL/TP, fee, slippage, and exit reason are persisted.
- [ ] No same-bar entry/exit look-ahead; stop-first treatment retained for OHLC ambiguity.
- [ ] News/event filter status is recorded for every accepted/rejected setup.

### Signal-state gates

- [ ] Regime test is more informative than one low ADX value and has a separately logged reason.
- [ ] Entry confirmation is deterministic and can be rerun from stored bars.
- [ ] Cost gate proves expected reward clears measured—not assumed—spread/fee/slippage.
- [ ] No hour/session rule is activated from fewer than a pre-specified minimum number of independent trades.

### Validation gates

- [ ] Development, validation, and final forward-paper holdout periods are frozen before evaluation.
- [ ] Net PF is above 1 after conservative costs in both validation and forward paper, with adequate sample size.
- [ ] Maximum drawdown, longest loss sequence, gap/slippage tail, and daily-loss kill switch meet pre-written limits.
- [ ] Sensitivity tests around parameters do not collapse outside one exact setting.
- [ ] A change that fails validation is documented and rejected rather than retuned on the holdout.

Until these are true, the correct bot action is **paper trade or remain flat**.
