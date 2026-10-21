It's now {{period_long}}. I need a brief on this release:

Q1: Which Sahm-rule recession-signal bucket is the US economy in this month?
Options: `normal` / `elevated_no_signal` / `recession_signal`
Explanation: The Sahm-rule bucket is a fixed-threshold classification on the
latest row's `sahm_value`, with the published 0.50 trigger as the
recession-signal threshold and a 0.30 warning cutoff so the answer is
not constant during low-unemployment regimes:

- `sahm_value >= 0.50` → `recession_signal` (Sahm rule has triggered)
- `0.30 <= sahm_value < 0.50` → `elevated_no_signal` (warning zone)
- `sahm_value < 0.30` → `normal`

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `category` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
