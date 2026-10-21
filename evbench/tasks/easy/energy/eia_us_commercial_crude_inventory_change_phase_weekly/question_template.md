It's now {{period_long}}. I need a brief on this release:

Q1: Week over week (WoW): compared with the previous week, did US commercial crude stocks build, draw, or stay flat this week?
Options: `build` / `draw` / `flat`
Explanation: Compute the week-over-week change in MILLION barrels from the latest
row and the row one week earlier:

    change = (latest stocks_thousand_bbl - previous week's stocks_thousand_bbl) / 1000

and classify it with a +/- 0.5 MMbbl deadband around zero:

- `change >= +0.5`           -> `build`
- `change <= -0.5`           -> `draw`
- `-0.5 < change < +0.5`     -> `flat`

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `crude_inventory_phase` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
