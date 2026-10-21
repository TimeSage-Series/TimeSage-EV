It's now ISO week {{iso_week_label}}. I need a brief on this release:

Q1: What is the MJO phase for this week?
Options: `weak` / `phase_1` / `phase_2` / `phase_3` / `phase_4` / `phase_5` / `phase_6` / `phase_7` / `phase_8`
Explanation: Compute the latest row's amplitude, `amplitude = sqrt(rmm1^2 + rmm2^2)`.
The MJO phase is classified by that amplitude and the
sign/sector of (rmm1, rmm2) in the Wheeler-Hendon phase plane:

- If `amplitude < 1.0`:  `weak`
- Else, the (rmm1, rmm2) point lies in one of eight 45-degree
  sectors of the phase plane:

  - `phase_1`: `rmm1 < 0` and `rmm2 < 0` and `|rmm1| >= |rmm2|`
  - `phase_2`: `rmm1 < 0` and `rmm2 < 0` and `|rmm1| <  |rmm2|`
  - `phase_3`: `rmm1 > 0` and `rmm2 < 0` and `rmm1   <  |rmm2|`
  - `phase_4`: `rmm1 > 0` and `rmm2 < 0` and `rmm1   >= |rmm2|`
  - `phase_5`: `rmm1 > 0` and `rmm2 > 0` and `rmm1   >  rmm2`
  - `phase_6`: `rmm1 > 0` and `rmm2 > 0` and `rmm1   <= rmm2`
  - `phase_7`: `rmm1 < 0` and `rmm2 > 0` and `|rmm1| <= rmm2`
  - `phase_8`: `rmm1 < 0` and `rmm2 > 0` and `|rmm1| >  rmm2`

This is the standard Wheeler & Hendon (2004) RMM phase wheel
convention (phase numbering increases counter-clockwise from the
Western Hemisphere / Africa sector).

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `mjo_phase` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
