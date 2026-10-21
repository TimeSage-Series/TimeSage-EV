It's now {{period_long}}. I need a brief on this release:

Q1: Read the latest row of `timeseries.csv` and report which retail diesel price band US #2 diesel pump prices fall into this week.
Options: `cheap` / `normal` / `elevated` / `extreme`
Explanation: The diesel price band is a fixed-threshold classification on the
latest row's `price_usd_per_gal`:

- `price_usd_per_gal < 3.50` -> `cheap`
- `3.50 <= price_usd_per_gal < 4.25` -> `normal`
- `4.25 <= price_usd_per_gal < 5.00` -> `elevated`
- `price_usd_per_gal >= 5.00` -> `extreme`

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `diesel_price_band` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
