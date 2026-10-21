It's now {{period_long}}. I need a brief on this release:

Q1: Which price band is WTI crude oil in this week?
Options: `low` / `normal` / `elevated` / `extreme`
Explanation: The price band is a fixed-threshold classification on the latest row's
`price_usd_per_bbl`:

- `price_usd_per_bbl >= 110` → `extreme`
- `90 <= price_usd_per_bbl < 110` → `elevated`
- `60 <= price_usd_per_bbl < 90` → `normal`
- `price_usd_per_bbl < 60` → `low`

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `category` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
