It's now {{period_long}}. I need a brief on this release:

Q1: Read the latest row of `timeseries.csv`, compute the 5-year same-MMWR-week percentile baseline from the CSV's history, and report which RSV seasonal phase US RSV positivity falls into this week.
Options: `off_season` / `active` / `elevated` / `peak`
Explanation: The RSV seasonal phase is a 4-way percentile cascade comparing the
latest row's `percent_pos` to the SAME MMWR week number's values from
the FIVE years immediately preceding the latest row's year:

1. Let the target year and target week be the year and ISO/MMWR week
   number of the latest row.
2. Collect `percent_pos` values from all rows whose MMWR week number
   equals the target week AND whose year is in the inclusive range from
   target year minus 5 through target year minus 1. Call this list the
   baseline.
3. Compute the 25th, 50th, and 75th percentiles of the baseline using
   Python's statistics quantiles function with n=4 (exclusive method).
   Call these p25, p50, and p75.
4. Classify the latest row's `percent_pos` value:

- `percent_pos` below p25 -> `off_season`
- `percent_pos` from p25 up to but not including p50 -> `active`
- `percent_pos` from p50 up to but not including p75 -> `elevated`
- `percent_pos` at or above p75 -> `peak`

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `rsv_phase` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
