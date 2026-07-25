# XAU compressed archive reconciliation

## File inspected

```text
origin/main:compressed_data.csv.gz
Git revision: 9ed6123
Compressed size: 17,858,671 bytes
Decompressed size: ~71 MB
Rows: 1,443,451 five-minute bars
Coverage: 2004-06-11 07:15 UTC → 2026-01-30 23:55 UTC
Schema: Date;Open;High;Low;Close;Volume
```

## Result

The archive is a valid gzip CSV and extends the available XAU history back to 2004. Its bars are chronologically ordered, have no duplicate timestamps, have internally valid OHLC values, and have positive volume.

However, it is **not a replacement source for the missing 2019–2026 data**. The supplied 2019–2026 CSV parts are an exact subset of this archive:

```text
Rows in existing 2019–2026 history: 443,451
Overlapping archive timestamps:      443,451
Exact OHLCV matches:                 443,451
Mismatched OHLCV rows:               0
```

Therefore, the archive preserves—not repairs—the two critical holes:

| Previous UTC bar | Next UTC bar | Missing duration | Gap jump |
|---|---|---:|---:|
| 2025-09-12 23:45 | 2025-10-15 07:55 | 32d 8h 10m | +14.723% |
| 2026-01-13 14:15 | 2026-01-22 18:50 | 9d 4h 35m | +6.496% |

## Additional historical-quality finding

The longer 2004–2019 section is less regular than the later history:

```text
Non-5m gaps in full archive: 27,563
Routine daily closures:     25,549
Weekend closures:            1,067
Other gaps requiring review:   947
Extended non-weekend gaps:      89
```

Many extended gaps are plausibly holidays or early closures. But the archive also has many intraday 95–195 minute interruptions, especially in the older section. It should **not** be treated as a clean, uninterrupted 22-year backtest source without the same gap policy.

## Decision

1. Keep the full archive as a useful historical reference and source for long-term market-regime exploration.
2. Do not use it to fill the two current critical gaps; it contains the exact same voids.
3. Do not merge another vendor's bars silently into this source.
4. For next backtests, use a gap guard and a clean continuous subset while a second source is obtained for the two critical windows.

## Needed replacement data

Obtain an independent, UTC 5-minute XAU/XAUUSD dataset for:

```text
2025-09-11 00:00 UTC → 2025-10-16 23:55 UTC
2026-01-12 00:00 UTC → 2026-01-23 23:55 UTC
```

A 24-hour buffer on each side permits overlap reconciliation. Required columns:

```text
Date;Open;High;Low;Close;Volume
```

If the replacement differs materially from the current vendor in the overlap region, it must be kept as a separate benchmark rather than merged into the canonical history.
