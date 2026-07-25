# XAU native M1 to M5 repair reconciliation

## Inputs

```text
Original M5 source:
  XAU_5m_data-part-011.csv … XAU_5m_data-part-015.csv
  Labelled Date field: broker server time, empirically Europe/Helsinki

Native M1 source:
  xauusd_2018_2026_7.csv … xauusd_2018_2026_10.csv
  Date + Timestamp field: empirically UTC
  Coverage: 2023-07-27 12:01 UTC → 2026-05-31 23:59 UTC
```

## Timezone finding

The original M5 labels cannot be UTC. A monthly return-alignment test shows that the M1 source aligns with M5 returns only after treating the M5 `Date` label as `Europe/Helsinki` and converting it to UTC:

```text
Northern winter: M5 label is UTC+2
Northern summer: M5 label is UTC+3
```

This matches the EET/EEST daylight-saving schedule. It also explains the apparent M5 daily closure near `00:00` in the raw file: in canonical UTC, it aligns with the M1 source's `21:00–22:00 UTC` maintenance/session closure.

**Consequences:** previous research that treated raw M5 labels as UTC has valid price bars but incorrect session/event placement. It must be re-run from the canonical UTC series before strategy conclusions are finalized.

## Overlap validation

After time normalization, native M1 bars were aggregated into complete M5 bars and compared to the original M5 source.

| Metric | Result |
|---|---:|
| Complete overlapping M5 bars | 169,471 |
| M5 return correlation | 0.997169 |
| Median absolute M5 return difference | 0.187 bps |
| Median absolute close difference | $0.125 |
| 95th-percentile absolute close difference | $0.342 |

This is strong evidence that the sources track the same underlying XAUUSD market closely enough for a **provenance-labelled repair**, not a blind merge.

## M1 quality

The M1 source is materially better than the rejected M3 archive:

```text
1,006,281 M1 rows
0 duplicate timestamps
0 out-of-order timestamps
0 invalid OHLC rows
0 zero-volume rows
```

It still has regular session/weekend closures and a few shorter intraday interruptions. The repair process accepts only exact M5 aggregates built from five contiguous native M1 bars; it does not create bars through those interruptions.

## Repair result

The reconciliation process creates a local canonical UTC M5 artifact with a `source` field:

```text
M5_ORIGINAL      original vendor bar, converted from Europe/Helsinki to UTC
M1_AGGREGATED    exact M5 aggregate of five contiguous native UTC M1 bars
```

```text
M1-derived M5 rows inserted: 8,455
Canonical rows:               451,906
```

The two critical M5 holes are covered substantially by native M1 data:

| Original gap | M1-derived M5 rows available | Residual caution |
|---|---:|---|
| 2025-09-12 → 2025-10-15 | 6,157 | Regular daily/weekend closures only in the requested repair span |
| 2026-01-13 → 2026-01-22 | 1,954 | One 3h40m Jan 19 interruption and one 10-minute Jan 20 interruption remain explicit gaps |

## Merge policy

1. Original M5 rows are never overwritten.
2. M1 is only used where an original M5 timestamp is absent.
3. M1 must form five contiguous UTC minutes before an M5 row is created.
4. Regular closures and residual M1 gaps remain visible; no interpolation is allowed.
5. All future backtests must use the canonical UTC timestamp and source/provenance fields.

## Next action

Re-run data quality and every XAU strategy comparison from this canonical UTC, M1-repaired history with a gap guard. The existing strategy results are now historical baseline artifacts, not final evidence.
