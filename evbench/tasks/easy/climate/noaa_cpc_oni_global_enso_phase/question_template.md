It's now {{period_long}}. I need a brief on this release:

Q1: What is the ENSO phase for this season?
Options: `El Nino` / `La Nina` / `ENSO-Neutral`
Explanation: NOAA CPC characterises each 3-month overlapping season by the ONI
anomaly value using a ±0.5 °C threshold. This scenario uses the
per-season threshold rule (NOT the 5-consecutive-season
confirmed-episode rule — a single season at the threshold counts; no
multi-season confirmation is required):

- `nino34_anomaly_c >= +0.5` → `El Nino`
- `nino34_anomaly_c <= -0.5` → `La Nina`
- otherwise → `ENSO-Neutral`

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `enso_phase` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
