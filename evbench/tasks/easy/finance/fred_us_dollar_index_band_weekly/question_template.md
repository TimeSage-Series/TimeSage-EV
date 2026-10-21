It's now {{period_long}}. I need a brief on this release:

Q1: Read the latest row of `timeseries.csv` and report which USD-strength band the FRED DTWEXBGS Broad Dollar Index falls into this week.
Options: `weak` / `normal` / `firm` / `strong` / `extreme`
Explanation: The USD-strength band is a fixed 5-way threshold cascade on the latest
row's `dxy_index`:

- `dxy_index < 118`             -> `weak`
- `118 <= dxy_index < 119`      -> `normal`
- `119 <= dxy_index < 120`      -> `firm`
- `120 <= dxy_index < 121`      -> `strong`
- `dxy_index >= 121`            -> `extreme`

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `dxy_band` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
