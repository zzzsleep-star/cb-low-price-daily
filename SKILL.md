---
name: cb-low-price-daily
description: Generate the latest daily top 10 Shanghai and Shenzhen convertible bonds using the exact low-price strategy rules from the completed historical backtest. Use for daily low-price bond screening, candidate lists, and scheduled strategy monitoring.
---

# Daily Convertible Bond Low-Price Screen

Run the self-contained `scripts/run_morning.py`. It creates and maintains its own local cache through AKShare; no pre-existing master table, historical database, or backtest framework is required. Preserve `references/strategy_rules.md`. Do not add conversion-premium, double-low, balance, industry, stock-return, 20-day zero-volume, or last-trading-day-over-20 filters.

## Workflow

1. Use Python containing AKShare, pandas, NumPy, PyArrow, Requests, and Tabulate.
2. Each morning, run `scripts/run_morning.py`. It identifies the latest exchange trading day strictly before the run date, discovers the current Shanghai/Shenzhen convertible-bond universe, builds missing master records, downloads the latest five sessions, checks redemption and stock-name risk states, and screens.
3. By default the cache is stored at `~/.cb-low-price-daily`. Override it with `--data-dir`:

   `python scripts/run_morning.py --data-dir <cache-directory>`

4. On the first run, allow extra time for basic-info and history requests. Later runs reuse the cache.
5. Call a result “上一交易日名单” only if the metadata confirms the target trading date and `official_full_universe_run` is true. If the calendar or market requests fail, keep the previous cache intact and report the failure.
6. Preserve sources. Do not silently hide request failures; return `failures.csv` and disclose missing coverage.
7. Return the ranked table, target date, freshness status, universe and eligible counts, sequential exclusion counts, output paths, and warnings.

Pass unknown stock-risk states only because the completed backtest used `risk_unknown_policy=pass`; disclose the unknown count. Exclude `decided_redeem` from `available_from` and reject a bond on or after `last_trade_date_event`.

Running on weekends or holidays still targets the most recent completed exchange trading day and does not fabricate a new date.
