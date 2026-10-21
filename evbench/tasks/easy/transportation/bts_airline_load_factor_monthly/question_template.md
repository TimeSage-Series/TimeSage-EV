It's now the {{period_label}} BTS airline passenger load factor release. I need a brief on this release:

Q1: Is this month's U.S. system-wide passenger load factor the highest reading in the trailing 12 months?
Options: `true` / `false`
Explanation:

- `is_year_high_load_factor`: TRUE iff the latest CSV row's
  `load_factor` is strictly greater than EACH of the eleven
  immediately preceding CSV rows' `load_factor` values (i.e. the
  latest reading is the strict maximum across the trailing 12 monthly
  observations, inclusive of itself). If fewer than 11 prior rows are
  available in `timeseries.csv`, set FALSE.

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `is_year_high_load_factor` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
