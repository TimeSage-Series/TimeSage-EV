It's now {{period_long}}. I need a brief on this release:

Q1: Which volatility regime is the VIX in this week?
Options: `low` / `normal` / `elevated` / `crisis`
Explanation: The volatility regime is a fixed-threshold classification on the
latest row's `vix_close`:

- `vix_close >= 40` → `crisis`
- `25 <= vix_close < 40` → `elevated`
- `15 <= vix_close < 25` → `normal`
- `vix_close < 15` → `low`

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `category` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
