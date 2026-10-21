It's now {{period_long}}. I need a brief on this release:

Q1: Read the latest row of `timeseries.csv` and report which refinery-utilization band US refineries fall into this week.
Options: `extreme_low` / `low` / `normal` / `high` / `extreme_high`
Explanation: The refinery-utilization band is a fixed 5-way threshold cascade on
the latest row's `utilization_pct`:

- `utilization_pct < 70` -> `extreme_low`
- `70 <= utilization_pct < 85` -> `low`
- `85 <= utilization_pct < 92` -> `normal`
- `92 <= utilization_pct < 96` -> `high`
- `utilization_pct >= 96` -> `extreme_high`

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `refinery_utilization_band` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
