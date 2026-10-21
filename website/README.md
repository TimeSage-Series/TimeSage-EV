# Project website

A static site with no build step: plain HTML, CSS and JavaScript.

```text
index.html          home: hero, results, releases, quickstart, scenarios, citation
scenarios.html      filterable list of every scenario
styles.css          light and dark themes
main.js             shared nav/footer plus the logic for both pages
data/scenarios.js   generated from evbench/maintainer/*/*/*/scenario.json
data/results.js     generated from the paper's result tables
build_data.py       regenerates data/scenarios.js
build_results.py    regenerates data/results.js
```

## Preview

Open `index.html` in a browser, or serve the folder:

```bash
python -m http.server -d website 8000   # then open http://localhost:8000
```

## Updating data

- **Scenarios**: after adding or refreshing scenarios, run `python website/build_data.py`.
  Periods and instance counts come from the released corpus in `evbench/scenarios`
  when it is present.
- **Releases**: each snapshot is one `<li class="tl-item">` in the `#releases`
  section of `index.html`. Copy the existing entry and put the newest first.
- **Tiers**: the site shows only the tiers listed in `TIERS` at the top of
  `main.js` (currently `['easy']`). Add `'middle'` and `'hard'` there to show
  them; the tier filters and the domain × tier matrix come back on their own.
- **Results**: run `python website/build_results.py <results dir>`, where the
  directory holds `single_vs_episode/` (currently
  `~/TimeSage-EV/workspace/cross_model_unweighted`, the equal-weight keypoint
  scores). `SVE_MODELS` in the script picks the models shown and their names.

## Deploying

`.github/workflows/pages.yml` publishes this folder to GitHub Pages on every
push to `master` that touches `website/`, at
<https://timesage-series.github.io/TimeSage-EV/>. It needs Settings → Pages →
Source set to **GitHub Actions** once. Any other static host works too.
