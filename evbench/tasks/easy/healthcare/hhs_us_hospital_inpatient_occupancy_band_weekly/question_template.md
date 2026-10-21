It's now {{period_long}}. I need a brief on this release:

Q1: Read the latest row of `timeseries.csv` and report which inpatient-occupancy band US hospitals fall into this week.
Options: `low` / `normal` / `elevated` / `surge`
Explanation: The hospital inpatient occupancy band is a fixed 4-way threshold
cascade on the latest row's `pctinptbedsocc`:

- `pctinptbedsocc < 70`            -> `low`
- `70 <= pctinptbedsocc < 73`      -> `normal`
- `73 <= pctinptbedsocc < 76`      -> `elevated`
- `pctinptbedsocc >= 76`           -> `surge`

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `occupancy_band` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
