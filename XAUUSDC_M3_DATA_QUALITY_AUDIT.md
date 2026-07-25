# XAUUSDc M3 archive assessment

## File inspected

```text
origin/main:XAUUSDc_M3_data.csv.gz
Git revision: 155f572
Compressed size: 9,888,956 bytes
Decompressed size: ~36 MB
Rows: 378,100 three-minute bars
Coverage: 2023-01-02 18:03 UTC → 2026-07-10 06:39 UTC
Schema: time, open, high, low, close, tick_volume, spread, hour, dayofweek, returns, volume
```

## What can be extracted safely in principle

A valid three-minute series can be aggregated exactly to timeframes divisible by three:

```text
15m  = 5 M3 bars
1H   = 20 M3 bars
4H   = 80 M3 bars
1D   = 480 M3 bars, subject to market closures
```

It **cannot** be converted into a true five-minute OHLC series. Three-minute and five-minute boundaries do not align; inventing M5 bars from M3 would create synthetic price paths and invalidate entry/stop ordering.

## Integrity result: reject as a fill source

The file has no duplicate timestamps, is monotonic, and has internally valid OHLC rows. Those basic checks are not enough. It has material quality problems:

```text
Zero tick_volume / volume rows: 297,138 of 378,100 (78.6%)
Non-3-minute gaps:              1,205
Recurring 60-minute gaps:         823
Recurring 120-minute gaps:         81
Largest gap: 61d 7h 3m
```

Most importantly, it contains repeated static bars that look like stale/template data rather than market prints.

| Finding | Evidence |
|---|---|
| Longest identical-bar run | 540 consecutive M3 rows from 2025-04-17 21:00 through 2025-04-18 23:57, all OHLC equal at 3326.925 with zero volume |
| Repeated nonzero template bar | One exact OHLCV tuple (`4339.265/4339.335/4333.098/4338.655`, volume 594) occurs **11,395 times** |
| December 2024 to March 2025 void | 61d 7h 3m gap, followed by a +9.282% open jump |
| Other issue | Many apparent Friday session rows are repeated flat values, not genuine M3 variation |

The M3 archive does cover the two missing M5 calendar windows, but it is a different source and its stale/repeated bars make it unsuitable for repairing or benchmarking the M5 history.

## Cross-source comparison

At normal overlapping daily observations, the median end-of-day difference from the M5 source is small (~0.002%). But the tails are materially different, especially in January 2026. For example, the M3 daily close is roughly 13% below the M5 source on several January 2026 dates because the M3 file contains the repeated 4338.655 template bar.

Therefore, the two datasets cannot be silently merged.

## Decision

```text
Do not use XAUUSDc_M3_data.csv.gz to fill M5 gaps.
Do not use its tick_volume or volume columns for order-flow research.
Do not use it as an independent clean M3 benchmark without first removing stale rows and proving source continuity.
```

## Required replacement format

To repair the M5 history, obtain native **M1 or M5** XAUUSD data from an independent source for:

```text
2025-09-11 00:00 UTC → 2025-10-16 23:55 UTC
2026-01-12 00:00 UTC → 2026-01-23 23:55 UTC
```

M1 is acceptable because it can be aggregated exactly to M5. M3 is not acceptable for M5 reconstruction.
