# XAU 5-minute data-quality audit

## Integrity checks

- Bars: **443,451**
- Data revision: `9229cd58ff171df61180c12e16fc35cc8b716343`
- Coverage: `2019-09-06T09:25:00+00:00` through `2026-01-30T23:55:00+00:00`
- Duplicate timestamps: **0**
- Out-of-order timestamp pairs: **0**
- Invalid OHLC rows: **0**
- Non-positive/invalid volume rows: **0**
- Price range: **$1445.57–$5597.60**

## Session pattern

The source is a weekday-only series. Most full days contain 274 or 276 bars rather than 288, consistent with a recurring around-midnight UTC maintenance/session closure. This is not automatically corruption, but every strategy must treat it as a non-tradable gap.

- Daily bar-count distribution: `{174: 1, 274: 691, 262: 19, 227: 12, 236: 4, 233: 1, 215: 2, 237: 7, 257: 1, 275: 24, 265: 1, 222: 1, 272: 2, 247: 3, 268: 1, 260: 1, 254: 1, 270: 2, 235: 1, 245: 5, 273: 1, 246: 19, 276: 814, 263: 1, 249: 2, 231: 2, 167: 1, 148: 1, 193: 1, 160: 1, 62: 1}`
- Total non-5m gaps: **1648**
- Gap categories: `{'weekend_closure': 315, 'regular_daily_closure': 1250, 'intraday_gap_requires_review': 60, 'extended_non_weekend_gap': 21, 'long_intraday_or_holiday_gap': 2}`
- Unresolved non-routine gaps: **83**
- Extended non-weekend gaps ≥24h: **21** (this includes documented holiday/early-close periods)
- Critical unexplained gaps >7 days: **2**

## Return sanity

- Largest single M5 close-to-close return: **+14.746%**
- Smallest single M5 close-to-close return: **-1.954%**
- 99th percentile absolute M5 close return: **0.220%**
- Largest inter-gap open jump: **+14.723%**
- Smallest inter-gap open jump: **-1.072%**

## Major unresolved gaps requiring source confirmation

| Previous UTC bar | Next UTC bar | Gap | Category | Open jump |
|---|---|---:|---|---:|
| 2025-09-12T23:45:00+00:00 | 2025-10-15T07:55:00+00:00 | 32d 8h 10m | extended_non_weekend_gap | +14.723% |
| 2026-01-13T14:15:00+00:00 | 2026-01-22T18:50:00+00:00 | 9d 4h 35m | extended_non_weekend_gap | +6.496% |
| 2020-12-24T20:40:00+00:00 | 2020-12-28T01:05:00+00:00 | 3d 4h 25m | extended_non_weekend_gap | +0.484% |
| 2020-12-31T20:45:00+00:00 | 2021-01-04T01:05:00+00:00 | 3d 4h 20m | extended_non_weekend_gap | +0.826% |
| 2024-03-28T22:55:00+00:00 | 2024-04-01T01:00:00+00:00 | 3d 2h 5m | extended_non_weekend_gap | +0.406% |
| 2023-12-29T23:40:00+00:00 | 2024-01-02T01:00:00+00:00 | 3d 1h 20m | extended_non_weekend_gap | +0.012% |
| 2020-04-09T23:50:00+00:00 | 2020-04-13T01:05:00+00:00 | 3d 1h 15m | extended_non_weekend_gap | -0.362% |
| 2021-04-01T23:50:00+00:00 | 2021-04-05T01:05:00+00:00 | 3d 1h 15m | extended_non_weekend_gap | -0.048% |
| 2021-12-23T23:50:00+00:00 | 2021-12-27T01:05:00+00:00 | 3d 1h 15m | extended_non_weekend_gap | -0.099% |
| 2022-04-14T23:50:00+00:00 | 2022-04-18T01:05:00+00:00 | 3d 1h 15m | extended_non_weekend_gap | -0.041% |
| 2022-12-30T23:45:00+00:00 | 2023-01-03T01:00:00+00:00 | 3d 1h 15m | extended_non_weekend_gap | +0.130% |
| 2022-12-23T23:55:00+00:00 | 2022-12-27T01:00:00+00:00 | 3d 1h 5m | extended_non_weekend_gap | +0.087% |
| 2023-04-06T23:55:00+00:00 | 2023-04-10T01:00:00+00:00 | 3d 1h 5m | extended_non_weekend_gap | -0.499% |
| 2023-12-22T23:55:00+00:00 | 2023-12-26T01:00:00+00:00 | 3d 1h 5m | extended_non_weekend_gap | +0.023% |
| 2025-04-17T23:55:00+00:00 | 2025-04-21T01:00:00+00:00 | 3d 1h 5m | extended_non_weekend_gap | +0.171% |
| 2019-12-24T20:25:00+00:00 | 2019-12-26T06:00:00+00:00 | 1d 9h 35m | extended_non_weekend_gap | +0.286% |
| 2019-12-31T20:45:00+00:00 | 2020-01-02T06:00:00+00:00 | 1d 9h 15m | extended_non_weekend_gap | -0.013% |
| 2024-12-24T20:40:00+00:00 | 2024-12-26T01:00:00+00:00 | 1d 4h 20m | extended_non_weekend_gap | -0.017% |
| 2025-12-24T20:40:00+00:00 | 2025-12-26T01:00:00+00:00 | 1d 4h 20m | extended_non_weekend_gap | +0.587% |
| 2024-12-31T23:45:00+00:00 | 2025-01-02T01:00:00+00:00 | 1d 1h 15m | extended_non_weekend_gap | -0.005% |

## Backtest consequence

The data passes basic OHLC ordering and positivity checks, but unresolved holes mean that an apparent outcome across a hole cannot be treated as a normal M5 trade path. Earlier results that allowed positions to remain open across an unresolved gap are provisional. Intraday research should either close positions before any non-routine gap or exclude the candidate/window; it must never invent missing bars or assume a stop/target sequence inside the void.

## Required remediation

1. **Mandatory:** obtain source-consistent UTC M5 replacement bars for the 32-day September–October 2025 void and the 9-day January 2026 void. These are not normal market closures.
2. Review shorter `intraday_gap_requires_review` rows against documented broker/exchange maintenance and holiday schedules. Many extended gaps are likely holiday/early-close periods and should remain explicit no-trade intervals, not be filled.
3. Keep routine daily maintenance, weekends, and documented holidays as explicit no-trade intervals rather than fabricating bars.
4. Re-run all strategy comparisons with a gap guard: no new position close to a non-routine gap; open positions are excluded/force-flattened at the last known pre-gap bar under a declared policy.
5. Do not use the present 2025 holdout as final evidence until the two critical voids are repaired or the affected dates are explicitly excluded from every comparison.

The machine-readable remediation list is [`XAU_DATA_QUALITY_GAPS.csv`](XAU_DATA_QUALITY_GAPS.csv).
