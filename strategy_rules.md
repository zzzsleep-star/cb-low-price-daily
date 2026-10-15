# Exact replicated strategy rules

At signal date `t` after close, start with bonds whose listing date is on or before `t` and whose delisting date is after `t`.

All conditions must pass:

1. The underlying stock is not in a known ST, *ST, delisting-risk, delisting-period, or terminated-listing state. The historical backtest passed unknown states and disclosed this limitation.
2. Issue bond rating is A+ or higher under `AAA > AA+ > AA > AA- > A+ > A > A- > BBB+ > BBB`. Unverified issue-rating semantics were allowed.
3. Contract maturity date minus `t` is at least 90 calendar days.
4. Sum of `amount_for_screening` over the latest five exchange trading days including `t` is at least RMB 50,000,000, with a complete five-session window.
5. Close is at least RMB 90. There is no upper price limit.
6. Open, close, and `volume_bonds` are present on `t`.
7. No `decided_redeem` event is effective; exclusion begins at `available_from`.
8. If an event last-trading date is known, `t` must be before it.

Sort eligible bonds by close ascending, then bond code ascending, and select the first 10. This selector creates a signal list; it does not simulate next-day execution.

The original framework used estimated `close × volume_bonds` turnover where actual turnover was unavailable. Keep `amount_for_screening_source` visible and disclose this approximation.
