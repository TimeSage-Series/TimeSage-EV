It's now MMWR week ending {{period_label}}. I need a brief on the LA-county NWSS COVID-19 wastewater activity for this week:

Q1: Week over week (WoW): compared with the previous MMWR week, is `site_wval` rising, falling, or stable this week?
Options: `rising` / `falling` / `stable`
Explanation: NWSS publishes `site_wval` weekly, a numeric activity index. The
WoW-direction tag is derived from the signed WoW % change in
`site_wval` against the prior MMWR week using a ±10% deadband: WoW%
above +10 → `rising`; WoW% below -10 → `falling`; otherwise → `stable`.

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `wow_direction` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
