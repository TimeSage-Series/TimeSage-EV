/* ════════════════════════════════════════════════════════════════
   TimeSage-EV · main.js
   Shared chrome (nav, footer, theme, reveal, copy) plus the logic for
   the home page and the scenarios page, selected by <body data-page>.
   ════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var REPO = 'https://github.com/TimeSage-Series/TimeSage-EV';
  var PAPER = 'https://arxiv.org/abs/2608.14270';
  var DATASET = 'https://huggingface.co/datasets/TimeSage-Series/TimeSage-EV';
  // Tiers shown on the site; add 'middle' and 'hard' here when they are released.
  var TIERS = ['easy'];
  var AXES = ['accuracy', 'coverage', 'faithfulness', 'quality'];
  var page = document.body.getAttribute('data-page');
  var SCENARIOS = (window.SCENARIOS || []).filter(function (s) { return TIERS.indexOf(s.tier) >= 0; });
  var RESULTS = window.RESULTS || {};

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function mean(xs) { return xs.reduce(function (a, b) { return a + b; }, 0) / xs.length; }
  function fmt(n) { return n.toFixed(1); }
  function store(key, val) {
    try { if (val === undefined) return localStorage.getItem(key); localStorage.setItem(key, val); } catch (e) { return null; }
  }

  /* ── Nav & footer ─────────────────────────────────────────────── */
  // A time series whose latest point sits inside a cycle: the analysis repeats with each release.
  var logo = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<rect x="1" y="1" width="22" height="22" rx="6" fill="var(--c-accent)"/>' +
    '<g stroke="var(--loop-on)" stroke-linecap="round" stroke-linejoin="round">' +
      '<polyline points="4.5,17.8 7.8,14.2 10.2,15.9 12.77,11.98" stroke-width="1.8"/>' +
      '<path d="M18.95,8.04 A3.7 3.7 0 1 1 14.04,6.25" stroke-width="1.3"/></g>' +
    '<polygon points="13.42,4.93 14.65,7.56 15.85,5.40" fill="var(--loop-on)"/>' +
    '<circle cx="15.6" cy="9.6" r="1.55" fill="var(--loop-on)"/></svg>';
  var home = page === 'home' ? '' : 'index.html';

  $('#site-nav').outerHTML =
    '<nav class="nav" id="nav"><div class="nav-inner">' +
      '<a class="nav-logo" href="index.html">' + logo + '<span>TimeSage-<span class="logo-ev">EV</span></span></a>' +
      '<div class="nav-links">' +
        '<a href="' + home + '#results">Results</a>' +
        '<a href="' + home + '#releases">Releases</a>' +
        '<a href="' + home + '#start">Quickstart</a>' +
        '<a href="scenarios.html"' + (page === 'scenarios' ? ' aria-current="page"' : '') + '>Scenarios</a>' +
      '</div>' +
      '<div class="nav-right">' +
        '<a class="icon-btn" href="' + REPO + '" target="_blank" rel="noopener" aria-label="GitHub repository">' +
          '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg></a>' +
        '<button class="icon-btn" id="theme-toggle" type="button" aria-label="Toggle dark mode">' +
          '<svg class="icon-sun" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="3"/><path d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3.05 3.05l1.06 1.06M11.89 11.89l1.06 1.06M3.05 12.95l1.06-1.06M11.89 4.11l1.06-1.06"/></svg>' +
          '<svg class="icon-moon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M13.5 9.5A5.5 5.5 0 016.5 2.5a5.5 5.5 0 107 7z"/></svg>' +
        '</button>' +
      '</div>' +
    '</div></nav>';

  $('#site-footer').outerHTML =
    '<footer class="footer"><div class="container footer-inner">' +
      '<div>TimeSage-EV · a live benchmark for agentic time series analysis</div>' +
      '<div class="footer-links">' +
        '<a href="' + REPO + '" target="_blank" rel="noopener">GitHub</a>' +
        '<a href="' + PAPER + '" target="_blank" rel="noopener">arXiv</a>' +
        '<a href="' + DATASET + '" target="_blank" rel="noopener">Hugging Face</a>' +
        '<a href="scenarios.html">Scenarios</a>' +
      '</div>' +
    '</div></footer>';

  $('#theme-toggle').addEventListener('click', function () {
    var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    store('theme', next);
  });

  var nav = $('#nav');
  function onScroll() { nav.classList.toggle('scrolled', window.scrollY > 8); }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  /* ── Reveal on scroll ─────────────────────────────────────────── */
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('visible'); io.unobserve(e.target); }
      });
    }, { threshold: 0.08 });
    $all('.reveal').forEach(function (el) { io.observe(el); });
  } else {
    $all('.reveal').forEach(function (el) { el.classList.add('visible'); });
  }

  /* ── Copy buttons ─────────────────────────────────────────────── */
  $all('[data-copy]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var text = document.getElementById(btn.getAttribute('data-copy')).textContent;
      var done = function () { btn.textContent = 'Copied'; setTimeout(function () { btn.textContent = 'Copy'; }, 1400); };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, function () {});
    });
  });

  if (page === 'home') initHome();
  if (page === 'scenarios') initScenarios();

  /* ════════════════════════════════════════════════════════════════
     HOME
     ════════════════════════════════════════════════════════════════ */
  function initHome() {
    runLoop();
    runTerminal();
    initComparisons();
    renderMatrix();
  }

  /* ── Analysis-loop animation ──────────────────────────────────── */
  // One lap per period: release → analysis → report → score & feedback.
  // The hub's series gains one release per period, cut at the release date;
  // after the last period it starts over. Reduced motion shows the final frame.
  function runLoop() {
    var NS = 'http://www.w3.org/2000/svg';
    var el = function (id) { return document.getElementById('loop-' + id); };
    var still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var LAP = 7000, R = 180, C = 280, TOTAL = 6;
    var ROLE = ['var(--loop-env)', 'var(--loop-agent)', 'var(--loop-agent)', 'var(--loop-eval)'];
    var HIST = 6, NPTS = HIST + TOTAL, X0 = 200, X1 = 360;
    var v = function (i) { return Math.sin(i * 0.55) + 0.35 * Math.sin(i * 1.3 + 1); };
    var px = function (i) { return X0 + i * (X1 - X0) / (NPTS - 1); };
    var py = function (i) { return 292 - v(i) * 30; };
    var period = still ? TOTAL : 1, t0 = performance.now();

    var dots = [];
    for (var i = 0; i < NPTS; i++) {
      var c = document.createElementNS(NS, 'circle');
      c.setAttribute('cx', px(i).toFixed(1)); c.setAttribute('cy', py(i).toFixed(1));
      c.setAttribute('r', '3'); c.setAttribute('class', 'pt');
      el('pts').appendChild(c); dots.push(c);
    }

    function drawSeries(f) {
      var last = HIST + period - 2, d = '';
      for (var i = 0; i <= last; i++) d += (d ? ' L' : 'M') + px(i).toFixed(1) + ' ' + py(i).toFixed(1);
      var ex = px(last) + (px(last + 1) - px(last)) * f, ey = py(last) + (py(last + 1) - py(last)) * f;
      d += ' L' + ex.toFixed(1) + ' ' + ey.toFixed(1);
      el('spark').setAttribute('d', d);
      dots.forEach(function (c, i) { c.style.opacity = i <= last ? '1' : '0'; });
      el('spark-end').setAttribute('cx', ex.toFixed(1)); el('spark-end').setAttribute('cy', ey.toFixed(1));
      el('cut').setAttribute('x1', ex.toFixed(1)); el('cut').setAttribute('x2', ex.toFixed(1));
    }

    function render(p) {
      var a = (-90 + 360 * p) * Math.PI / 180;
      var x = (C + R * Math.cos(a)).toFixed(1), y = (C + R * Math.sin(a)).toFixed(1);
      ['dot', 'glow'].forEach(function (id) { el(id).setAttribute('cx', x); el(id).setAttribute('cy', y); });
      for (var i = 0; i < 4; i++) {
        var len = Math.max(0, Math.min(25, p * 100 - 25 * i));
        el('s' + i).setAttribute('stroke-dasharray', len.toFixed(2) + ' 100');
      }
      drawSeries(still ? 1 : Math.min(1, p / 0.2));
      var col = ROLE[Math.min(3, Math.floor(p * 4))];
      el('dot').style.fill = col; el('glow').style.fill = col;
      var active = still ? -1 : Math.floor((p * 4 + 0.5) % 4);
      for (var j = 0; j < 4; j++) {
        el('n' + j).classList.toggle('on', j === active);
        el('l' + j).classList.toggle('on', j === active);
      }
      el('pnum').textContent = period;
    }

    function frame(now) {
      var elapsed = now - t0;
      if (elapsed >= LAP) {
        t0 += LAP; elapsed -= LAP;
        period = period >= TOTAL ? 1 : period + 1;
      }
      render(elapsed / LAP);
      requestAnimationFrame(frame);
    }

    if (still) render(1);
    else requestAnimationFrame(frame);
  }

  /* ── Terminal animation ───────────────────────────────────────── */
  // Types an `evsandbox episode` command and prints per-period scores;
  // starts when the terminal scrolls into view, then repeats.
  function runTerminal() {
    var body = $('#terminal-body');
    var cmd = 'evsandbox episode \\\n    evbench/scenarios/easy/climate/noaa_cpc_ao_monthly_phase \\\n    --config experiments/mine.yaml';
    var periods = [
      ['2024-07', 41.2, 92.0, 70.0, 64.5],
      ['2024-08', 100.0, 94.5, 85.0, 71.0],
      ['2024-09', 100.0, 96.0, 90.0, 74.5],
      ['2024-10', 100.0, 97.5, 90.0, 78.0],
      ['2024-11', 100.0, 98.0, 95.0, 80.5],
      ['2024-12', 100.0, 97.0, 95.0, 81.0]
    ];
    function score(v) {
      var cls = v >= 80 ? 't-ok' : v >= 50 ? 't-hi' : 't-bad';
      return ' <span class="' + cls + '">' + (v < 100 ? ' ' : '') + v.toFixed(1) + '</span>';
    }
    var lines = [
      '<span class="t-dim">  sandbox  cutoff-truncated · bwrap · net audited</span>',
      '<span class="t-dim">  agent    timesage_agent · feedback=score</span>',
      ''
    ];
    periods.forEach(function (p, i) {
      lines.push('<b>' + (i + 1) + '/24</b> <b>' + p[0] + '</b> <span class="t-ok">●</span>' +
        ' <span class="t-blue">acc</span>' + score(p[1]) + ' <span class="t-blue">cov</span>' + score(p[2]) +
        ' <span class="t-blue">fth</span>' + score(p[3]) + ' <span class="t-blue">qlt</span>' + score(p[4]));
      if (i === 0) lines.push('<span class="t-dim">  ↳ skill saved: classify_ao_phase(ao_value)</span>');
      if (i === 1) lines.push('<span class="t-dim">  ↳ reused skill: classify_ao_phase</span>');
    });
    lines.push('<span class="t-dim">  …</span>');

    var prompt = '<span class="t-prompt">$</span> ';
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      body.innerHTML = prompt + esc(cmd) + '\n' + lines.join('\n');
      return;
    }

    function play() {
      var typed = 0;
      (function type() {
        body.innerHTML = prompt + esc(cmd.slice(0, typed)) + '<span class="cursor"></span>';
        if (typed < cmd.length) { typed += 2; setTimeout(type, 28); return; }
        var shown = 0;
        (function emit() {
          body.innerHTML = prompt + esc(cmd) + '\n' + lines.slice(0, shown).join('\n') + '\n<span class="cursor"></span>';
          if (shown < lines.length) { shown++; setTimeout(emit, shown < 3 ? 260 : 620); return; }
          setTimeout(play, 5200);
        })();
      })();
    }

    if (!('IntersectionObserver' in window)) { play(); return; }
    var io = new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting) { io.disconnect(); play(); }
    }, { threshold: 0.3 });
    io.observe(body);
  }

  function bindSeg(sel, onChange) {
    var root = $(sel);
    root.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      $all('button', root).forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
      onChange(b.getAttribute('data-v'));
    });
  }

  // Tier pickers are built from TIERS and hidden while only one tier is released.
  function tierControl(sel, onChange) {
    var root = $(sel);
    if (TIERS.length < 2) { root.closest('[data-tier-control]').hidden = true; return; }
    root.innerHTML = ['all'].concat(TIERS).map(function (t, i) {
      return '<button type="button" data-v="' + t + '" aria-pressed="' + (i === 0) + '">' + t.charAt(0).toUpperCase() + t.slice(1) + '</button>';
    }).join('');
    bindSeg(sel, onChange);
  }

  /* ── Sequential vs. independent charts ────────────────────────── */
  // One card per model: mean scores for the first released tier and the
  // per-period curves of both modes.
  function initComparisons() {
    var runs = RESULTS.single_vs_episode || [];
    var tier = TIERS[0];
    $('#sve-grid').innerHTML = runs.map(function (s) {
      var t = s.tiers[tier], gain = t.episode - t.single;
      return '<div class="chart-card">' +
        '<div class="chart-title">' + esc(s.model) + '</div>' +
        '<div class="sve-stats">' +
          '<div><span class="sve-num" style="color:var(--c-accent)">' + fmt(t.episode) + '</span><span class="sve-label">Sequential</span></div>' +
          '<div><span class="sve-num" style="color:var(--c-muted)">' + fmt(t.single) + '</span><span class="sve-label">Independent</span></div>' +
          '<div><span class="sve-num ' + (gain >= 0 ? 'gain-pos' : 'gain-neg') + '">' + signed(gain) + '</span><span class="sve-label">Gain</span></div>' +
        '</div>' +
        '<div class="chart-host"><svg viewBox="0 0 520 300" preserveAspectRatio="xMidYMid meet" role="img" aria-label="' +
          esc(s.model) + ': per-period score, sequential versus independent"></svg><div class="tooltip"></div></div>' +
      '</div>';
    }).join('');
    $all('#sve-grid .chart-card').forEach(function (card, i) { drawComparison(card, runs[i].curves[tier]); });
  }

  function signed(d) { return (d >= 0 ? '+' : '−') + fmt(Math.abs(d)); }

  function drawComparison(card, c) {
    var el = $('svg', card), tip = $('.tooltip', card), host = $('.chart-host', card);
    var ep = c.episode, ind = c.single, n = ep.length;
    var W = 520, H = 300, L = 34, R = 12, T = 12, B = 30;
    var all = ep.concat(ind);
    var lo = Math.max(0, Math.floor((Math.min.apply(null, all) - 5) / 10) * 10);
    var hi = Math.min(100, Math.ceil((Math.max.apply(null, all) + 5) / 10) * 10);
    var x = function (i) { return L + (W - L - R) * i / (n - 1); };
    var y = function (v) { return T + (H - T - B) * (1 - (v - lo) / (hi - lo)); };
    var path = function (vs) { return vs.map(function (v, i) { return (i ? 'L' : 'M') + x(i).toFixed(1) + ',' + y(v).toFixed(1); }).join(' '); };

    var svg = '<g class="grid">';
    for (var v = lo; v <= hi; v += 10) {
      svg += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '"/>' +
             '<text class="axis-text" x="' + (L - 8) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + v + '</text>';
    }
    svg += '</g>';
    for (var i = 0; i < n; i++) {
      if (i % 4 === 0 || i === n - 1) svg += '<text class="axis-text" x="' + x(i) + '" y="' + (H - 8) + '" text-anchor="middle">P' + (i + 1) + '</text>';
    }
    var area = path(ep) + ' ' + ind.slice().reverse().map(function (v, j) { return 'L' + x(n - 1 - j).toFixed(1) + ',' + y(v).toFixed(1); }).join(' ') + ' Z';
    svg += '<path class="area-gain" d="' + area + '"/>';
    svg += '<path class="line-independent" d="' + path(ind) + '"/>';
    svg += '<path class="line-episode" d="' + path(ep) + '"/>';
    svg += '<circle class="dot-episode" cx="' + x(n - 1) + '" cy="' + y(ep[n - 1]) + '" r="4"/>';
    svg += '<circle class="dot-independent" cx="' + x(n - 1) + '" cy="' + y(ind[n - 1]) + '" r="3.5"/>';
    svg += '<line class="hover-line" x1="0" x2="0" y1="' + T + '" y2="' + (H - B) + '" style="display:none"/>';
    svg += '<rect class="hover-rect" x="' + L + '" y="' + T + '" width="' + (W - L - R) + '" height="' + (H - T - B) + '" fill="transparent"/>';
    el.innerHTML = svg;

    var line = $('.hover-line', el), rect = $('.hover-rect', el);
    rect.addEventListener('mousemove', function (e) {
      var box = el.getBoundingClientRect();
      var sx = (e.clientX - box.left) * W / box.width;
      var i = Math.max(0, Math.min(n - 1, Math.round((sx - L) / (W - L - R) * (n - 1))));
      line.setAttribute('x1', x(i)); line.setAttribute('x2', x(i)); line.style.display = '';
      tip.innerHTML = '<div class="tt-head">Period ' + (i + 1) + '</div>' +
        '<div style="color:var(--c-accent)">sequential ' + fmt(ep[i]) + '</div>' +
        '<div style="color:var(--c-muted)">independent ' + fmt(ind[i]) + '</div>' +
        '<div>gain ' + signed(ep[i] - ind[i]) + '</div>';
      var px = x(i) * box.width / W;
      tip.style.left = Math.min(px + 12, host.clientWidth - tip.offsetWidth - 4) + 'px';
      tip.style.top = (y(Math.max(ep[i], ind[i])) * box.height / H) + 'px';
      tip.style.opacity = 1;
    });
    rect.addEventListener('mouseleave', function () { tip.style.opacity = 0; line.style.display = 'none'; });
  }

  /* ── Scenario overview: domain cards, or a domain × tier matrix ── */
  function renderMatrix() {
    var domains = Array.from(new Set(SCENARIOS.map(function (s) { return s.domain; }))).sort();
    var count = function (d, t) { return SCENARIOS.filter(function (s) { return (!d || s.domain === d) && (!t || s.tier === t); }).length; };
    var multi = TIERS.length > 1;
    if (!multi) {
      $('#scenario-overview').innerHTML = '<div class="domain-grid">' + domains.map(function (d) {
        var items = SCENARIOS.filter(function (s) { return s.domain === d; });
        return '<a class="domain-card" href="scenarios.html?domain=' + d + '">' +
          '<div class="domain-head"><span class="domain-name">' + esc(d) + '</span><span class="domain-count">' + items.length + '</span></div>' +
          '<ul>' + items.map(function (s) { return '<li>' + esc(s.name) + '</li>'; }).join('') + '</ul></a>';
      }).join('') + '</div>';
      return;
    }
    var html = '<thead><tr><th></th>' + TIERS.map(function (t) {
      return '<th><span class="tier-badge tier-' + t + '">' + t + '</span></th>';
    }).join('') + (multi ? '<th>Total</th>' : '') + '</tr></thead><tbody>';
    domains.forEach(function (d) {
      html += '<tr><th class="row-h">' + esc(d) + '</th>' + TIERS.map(function (t) {
        return '<td><a href="scenarios.html?domain=' + d + (multi ? '&tier=' + t : '') + '" aria-label="' + count(d, t) + ' ' + t + ' ' + d + ' scenarios">' + count(d, t) + '</a></td>';
      }).join('') + (multi ? '<td class="total">' + count(d) + '</td>' : '') + '</tr>';
    });
    html += '<tr><th class="row-h" style="color:var(--c-dim)">Total</th>' + TIERS.map(function (t) {
      return '<td class="total">' + count(null, t) + '</td>';
    }).join('') + (multi ? '<td class="total">' + SCENARIOS.length + '</td>' : '') + '</tr></tbody>';
    $('#scenario-overview').innerHTML = '<div class="table-wrap" style="border:0"><table class="matrix">' + html + '</table></div>';
  }

  /* ════════════════════════════════════════════════════════════════
     SCENARIOS PAGE
     ════════════════════════════════════════════════════════════════ */
  function initScenarios() {
    var params = new URLSearchParams(location.search);
    var domainSel = $('#f-domain'), cadenceSel = $('#f-cadence'), search = $('#f-search');
    var uniq = function (k) { return Array.from(new Set(SCENARIOS.map(function (s) { return s[k]; }))).sort(); };
    domainSel.innerHTML = '<option value="">All domains</option>' + uniq('domain').map(function (d) {
      return '<option value="' + d + '">' + d.charAt(0).toUpperCase() + d.slice(1) + '</option>';
    }).join('');
    cadenceSel.innerHTML = '<option value="">Any cadence</option>' + uniq('cadence').map(function (c) {
      return '<option value="' + c + '">' + c + '</option>';
    }).join('');

    var tier = params.get('tier');
    var state = { tier: TIERS.indexOf(tier) >= 0 ? tier : 'all', domain: params.get('domain') || '', cadence: '', q: '' };
    domainSel.value = state.domain;
    tierControl('#f-tier', function (v) { state.tier = v; render(); });
    $all('#f-tier button').forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-v') === state.tier)); });

    function render() {
      var q = state.q.toLowerCase();
      var rs = SCENARIOS.filter(function (s) {
        return (state.tier === 'all' || s.tier === state.tier) &&
               (!state.domain || s.domain === state.domain) &&
               (!state.cadence || s.cadence === state.cadence) &&
               (!q || (s.name + ' ' + s.title + ' ' + s.id + ' ' + s.publisher + ' ' + s.source_name).toLowerCase().indexOf(q) >= 0);
      });
      $('#result-count').textContent = rs.length + ' of ' + SCENARIOS.length;
      $('#sc-body').innerHTML = rs.map(function (s) {
        var src = s.source_url ? '<a href="' + esc(s.source_url) + '" target="_blank" rel="noopener">' + esc(s.source_name || s.source_url) + ' ↗</a>' : esc(s.source_name);
        return '<tr>' +
          '<td><div class="sc-title">' + esc(s.name) + '</div><div class="sc-id">' + esc(s.id) + '</div></td>' +
          '<td><span class="tier-badge tier-' + s.tier + '">' + s.tier + '</span></td>' +
          '<td class="sc-domain">' + esc(s.domain) + '</td>' +
          '<td class="sc-pub">' + src + '</td>' +
          '<td class="sc-mono">' + esc(s.cadence) + '</td>' +
          '<td class="sc-mono">' + esc(s.first) + ' → ' + esc(s.last) + '</td>' +
          '<td class="sc-mono" style="text-align:right">' + s.instances + '</td>' +
        '</tr>';
      }).join('') || '<tr class="empty-row"><td colspan="7">No scenarios match these filters.</td></tr>';
    }

    domainSel.addEventListener('change', function () { state.domain = domainSel.value; render(); });
    cadenceSel.addEventListener('change', function () { state.cadence = cadenceSel.value; render(); });
    search.addEventListener('input', function () { state.q = search.value.trim(); render(); });
    render();
  }
})();
