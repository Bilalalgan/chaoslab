/* ChaosLab – istemci: görünüm oluşturma, API, Plotly grafikleri (sürekli + ayrık sistemler) */
"use strict";

const VARS = ["x", "y", "z", "w"];
const MAX_DIM = 10;
const $ = (id) => document.getElementById(id);
/* N ≤ 4: x, y, z, w ; N > 4: x1 … xN (sunucu ile aynı kural) */
function varNames(n) { return n <= 4 ? VARS.slice(0, n) : Array.from({ length: n }, (_, i) => `x${i + 1}`); }
function vtex(v) { return v.length > 1 ? `${v[0]}_{${v.slice(1)}}` : v; }
function colorOf(th, v, i = 0) { return th.c[v] || th.pal[i % th.pal.length]; }
const PLOT_CONFIG = {
  responsive: true, displaylogo: false,
  modeBarButtonsToRemove: ["lasso2d", "select2d"],
  toImageButtonOptions: { format: "png", scale: 2 },
};
const FS = { tick: 14, axis: 17, title: 17, legend: 13, tick3d: 12, axis3d: 15 };

/* ================================================================ tema */
function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
function TH() {
  const th = TH0();
  for (let i = 1; i <= MAX_DIM; i++) th.c[`x${i}`] = th.pal[(i - 1) % th.pal.length];
  return th;
}
function TH0() {
  return {
    bg: cssVar("--plot-bg"), grid: cssVar("--plot-grid"), zero: cssVar("--plot-zero"),
    tick: cssVar("--plot-tick"), title: cssVar("--plot-title"), legendBg: cssVar("--plot-legend-bg"),
    hoverBg: cssVar("--plot-hover-bg"), scene: cssVar("--plot-scene"), font: cssVar("--font"), mono: cssVar("--mono"),
    accent: cssVar("--cyan"), good: cssVar("--green"), bad: cssVar("--red"), amber: cssVar("--amber"),
    violet: cssVar("--violet"), pink: cssVar("--pink"), faint: cssVar("--text-faint"),
    c: { x: cssVar("--c-x"), y: cssVar("--c-y"), z: cssVar("--c-z"), w: cssVar("--c-w") },
    pal: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => cssVar(`--p${i}`)),
  };
}

function baseLayout(extra = {}) {
  const th = TH();
  const axis = {
    gridcolor: th.grid, zerolinecolor: th.zero, linecolor: th.zero, automargin: true,
    tickfont: { family: th.mono, size: FS.tick, color: th.tick },
    title: { font: { family: th.font, size: FS.axis, color: th.title } },
  };
  const layout = {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: th.bg,
    font: { family: th.font, color: th.title, size: 13 },
    margin: { l: 70, r: 20, t: 40, b: 60 },
    legend: { bgcolor: th.legendBg, bordercolor: th.grid, borderwidth: 1, font: { size: FS.legend } },
    hoverlabel: { bgcolor: th.hoverBg, bordercolor: th.accent, font: { family: th.mono, size: 12, color: th.title } },
    xaxis: deepMerge({}, axis), yaxis: deepMerge({}, axis),
  };
  return deepMerge(layout, extra);
}
function axisStyle() { return baseLayout().xaxis; }
function deepMerge(a, b) {
  const out = { ...a };
  for (const [k, v] of Object.entries(b)) {
    out[k] = v && typeof v === "object" && !Array.isArray(v) && a[k] && typeof a[k] === "object" && !Array.isArray(a[k])
      ? deepMerge(a[k], v) : v;
  }
  return out;
}
function ax(text, extra = {}) { return deepMerge({ title: { text } }, extra); }
function ttl(text) { return { text, font: { size: FS.title } }; }
function sceneAxis(title) {
  const th = TH();
  return {
    title: { text: title, font: { family: th.mono, size: FS.axis3d, color: th.title } },
    backgroundcolor: th.scene, gridcolor: th.grid, zerolinecolor: th.zero,
    showbackground: true, tickfont: { family: th.mono, size: FS.tick3d, color: th.tick },
  };
}

/* ================================================================ yardımcılar */
function tex(el, latex, display = false) {
  if (!el) return;
  try { katex.render(latex, el, { displayMode: display, throwOnError: false, strict: "ignore" }); }
  catch (err) { el.textContent = latex; }
}
function renderStaticTex(root = document) { root.querySelectorAll("[data-tex]").forEach((el) => tex(el, el.dataset.tex, false)); }
function fmt(v, digits = 5) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-3 || a >= 1e5)) return v.toExponential(3);
  return Number(v.toPrecision(digits)).toString();
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fillSelect(sel, options, value, labels) {
  sel.innerHTML = options.map((o, i) => `<option value="${escapeHtml(o)}">${escapeHtml(labels ? labels[i] : o)}</option>`).join("");
  if (value !== undefined && options.map(String).includes(String(value))) sel.value = value;
}
function setBusy(btn, busy) {
  btn.disabled = busy;
  const sp = btn.querySelector(".spinner-border");
  if (sp) sp.classList.toggle("d-none", !busy);
}
function nloc() { return I18N.lang === "en" ? "en-US" : "tr-TR"; }
function resizeVisiblePlots() {
  document.querySelectorAll(".view:not(.d-none) .tab-pane.active .js-plotly-plot").forEach((el) => Plotly.Plots.resize(el));
}
async function api(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    if (data && data.detail) {
      msg = Array.isArray(data.detail)
        ? data.detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join(" | ")
        : trB(data.detail);
    }
    throw new Error(msg);
  }
  return data;
}

/* ================================================================ görünüm şablonu */
function T(key) { return `<span data-i18n="${key}"></span>`; }
function numIn(id, label, attrs = "") {
  return `<label class="form-label" for="${id}">${label}</label><input id="${id}" type="number" step="any" class="form-control form-control-sm mono" ${attrs}>`;
}
function plotCard(id, cls, head = "") {
  return `<div class="card-lab">${head ? `<div class="card-head">${head}</div>` : ""}<div id="${id}" class="plot ${cls}"></div></div>`;
}

function buildView(kind) {
  const p = kind === "ode" ? "o" : "m";
  const ode = kind === "ode";
  const dims = ode ? [2, 3, 4, 5, 6] : [1, 2, 3, 4, 5];

  const sidebar = `
  <aside class="sidebar">
    <form id="${p}-form" autocomplete="off" novalidate>
      <section class="panel">
        <div class="panel-title">${T("presetSystem")}</div>
        <select id="${p}-preset" class="form-select form-select-sm"><option value="custom" data-i18n="customSystem"></option></select>
        <div class="dim-row mt-2">
          <span class="form-label m-0">${T("dimN")}</span>
          <div class="btn-group btn-group-sm" role="group">
            ${dims.map((d) => `<button type="button" class="btn btn-outline-info dim-quick" data-dim="${d}">${d}</button>`).join("")}
          </div>
          <input id="${p}-dim-n" type="number" min="1" max="${MAX_DIM}" step="1" class="form-control form-control-sm mono dim-input" data-i18n-title="dimTitle">
        </div>
      </section>
      <section class="panel">
        <div class="panel-title">${T(ode ? "odeEquations" : "mapEquations")}</div>
        <div id="${p}-eqs"></div>
        <div class="hint" id="${p}-vars-hint"></div>
        <div class="hint" data-i18n-html="${ode ? "eqHintOde" : "eqHintMap"}"></div>
      </section>
      <section class="panel">
        <div class="panel-title">${T("parameters")}</div>
        <textarea id="${p}-params" class="form-control form-control-sm mono" rows="2" spellcheck="false"></textarea>
        <div class="panel-title mt-3">${T("initialConditions")} <span data-tex="\\mathbf{x}_0"></span></div>
        <div class="ic-grid" id="${p}-ics"></div>
      </section>
      <section class="panel">
        <div class="panel-title">${T("simSettings")}</div>
        <div class="row g-2">
          ${ode ? `
          <div class="col-6">${numIn(`${p}-t-max`, "t<sub>max</sub>", 'min="0"')}</div>
          <div class="col-6">${numIn(`${p}-dt`, "Δt", 'min="0"')}</div>
          <div class="col-6">${numIn(`${p}-delta0`, `${T("perturbation")} δ₀`, 'min="0"')}</div>
          <div class="col-6"><label class="form-label" for="${p}-method">${T("method")}</label>
            <select id="${p}-method" class="form-select form-select-sm"><option value="DOP853" selected>DOP853</option><option value="RK45">RK45</option><option value="LSODA">LSODA</option><option value="Radau">Radau</option></select></div>`
          : `
          <div class="col-6">${numIn(`${p}-n-iter`, `${T("iterations")} N`, 'min="20"')}</div>
          <div class="col-6">${numIn(`${p}-transient`, T("transientIter"), 'min="0"')}</div>
          <div class="col-6">${numIn(`${p}-delta0`, `${T("perturbation")} δ₀`, 'min="0"')}</div>`}
        </div>
        <div class="panel-title mt-3 d-flex justify-content-between align-items-center">
          <span>${T("lyapQR")}</span>
          <div class="form-check form-switch m-0"><input class="form-check-input" type="checkbox" id="${p}-compute-lyap" checked><label class="form-check-label small" for="${p}-compute-lyap">${T("compute")}</label></div>
        </div>
        <div class="row g-2">
          ${ode ? `
          <div class="col-4">${numIn(`${p}-lyap-t`, "T", 'min="0"')}</div>
          <div class="col-4">${numIn(`${p}-lyap-dt`, "Δt", 'min="0"')}</div>
          <div class="col-4">${numIn(`${p}-lyap-tr`, T("transient"), 'min="0"')}</div>`
          : `<div class="col-6">${numIn(`${p}-lyap-n`, `${T("iterations")} N`, 'min="10"')}</div>`}
        </div>
      </section>
      <button type="submit" id="${p}-analyze-btn" class="btn btn-analyze w-100">
        <span class="spinner-border spinner-border-sm me-2 d-none" role="status"></span>${T("analyzeBtn")}
      </button>
      <div id="${p}-status" class="status-line" data-i18n="ready"></div>
    </form>
  </aside>`;

  const kpis = `
  <section class="kpi-grid">
    <div class="kpi"><div class="kpi-label">${T("kpiDim")}</div><div class="kpi-value" id="${p}-kpi-dim">—</div><div class="kpi-sub" id="${p}-kpi-dim-sub" data-i18n="stateVars"></div></div>
    <div class="kpi"><div class="kpi-label">${T(ode ? "kpiAuto" : "kpiMapType")}</div><div class="kpi-value" id="${p}-kpi-2">—</div><div class="kpi-sub" id="${p}-kpi-2-sub">—</div></div>
    <div class="kpi"><div class="kpi-label">${ode ? `${T("kpiDiv")} ∇·F` : `${T("kpiDet")} |det J|`}</div><div class="kpi-value" id="${p}-kpi-3">—</div><div class="kpi-sub" id="${p}-kpi-3-sub">—</div></div>
    <div class="kpi"><div class="kpi-label">${T("kpiClass")}</div><div class="kpi-value" id="${p}-kpi-class">—</div><div class="kpi-sub" id="${p}-kpi-class-sub" data-i18n="lyapDiag"></div></div>
    <div class="kpi"><div class="kpi-label">${T("kpiDky")}</div><div class="kpi-value" id="${p}-kpi-dky">—</div><div class="kpi-sub" data-tex="D_{KY}"></div></div>
    <div class="kpi"><div class="kpi-label">${T("kpiD2")}</div><div class="kpi-value" id="${p}-kpi-d2">—</div><div class="kpi-sub" id="${p}-kpi-d2-sub" data-tex="D_2 \\;/\\; D_0"></div></div>
  </section>`;

  const tabs = [
    ["phase", ode ? "tabPhase" : "tabOrbit"],
    ["time", "tabTime"],
    ["eq", ode ? "tabEq" : "tabFixed"],
    ["lyap", "tabLyap"],
    ["bif", ode ? "tabBif" : "tabOrbitDiag"],
    ...(ode ? [["pc", "tabPoincare"]] : []),
    ["basin", "tabBasin"],
    ["spec", "tabSpectrum"],
    ["frac", "tabFractal"],
    ["cmp", "tabCompare"],
  ];
  const tabNav = `<ul class="nav nav-tabs lab-tabs" role="tablist">${tabs.map(([k, key], i) =>
    `<li class="nav-item" role="presentation"><button class="nav-link ${i === 0 ? "active" : ""}" data-bs-toggle="tab" data-bs-target="#${p}-tab-${k}" type="button" role="tab" data-i18n="${key}"></button></li>`).join("")}</ul>`;

  const phaseTab = ode ? `
      <div class="toolbar">
        <div class="toolbar-group need-2"><span class="toolbar-label">${T("axes")}</span>
          <select id="${p}-ax-1" class="form-select form-select-sm axis-select"></select>
          <select id="${p}-ax-2" class="form-select form-select-sm axis-select"></select>
          <select id="${p}-ax-3" class="form-select form-select-sm axis-select need-3"></select></div>
        <div class="toolbar-group">
          <div class="form-check form-switch m-0"><input class="form-check-input" type="checkbox" id="${p}-color-time" checked><label class="form-check-label small" for="${p}-color-time">${T("colorByTime")}</label></div>
          <div class="form-check form-switch m-0"><input class="form-check-input" type="checkbox" id="${p}-show-eq" checked><label class="form-check-label small" for="${p}-show-eq">${T("equilibria")}</label></div>
        </div>
      </div>
      ${plotCard(`${p}-plot-3d`, "plot-tall")}
      <div class="row g-3 mt-0 need-3">
        <div class="col-xl-4 col-md-6">${plotCard(`${p}-plot-p1`, "plot-sq")}</div>
        <div class="col-xl-4 col-md-6">${plotCard(`${p}-plot-p2`, "plot-sq")}</div>
        <div class="col-xl-4 col-md-12">${plotCard(`${p}-plot-p3`, "plot-sq")}</div>
      </div>` : `
      <div class="toolbar">
        <div class="toolbar-group need-2"><span class="toolbar-label">${T("axes")}</span>
          <select id="${p}-ax-1" class="form-select form-select-sm axis-select"></select>
          <select id="${p}-ax-2" class="form-select form-select-sm axis-select"></select>
          <select id="${p}-ax-3" class="form-select form-select-sm axis-select need-3"></select></div>
        <div class="toolbar-group"><span class="toolbar-label">${T("returnMapVar")}</span>
          <select id="${p}-rm-var" class="form-select form-select-sm axis-select"></select>
          <div class="form-check form-switch m-0"><input class="form-check-input" type="checkbox" id="${p}-show-eq" checked><label class="form-check-label small" for="${p}-show-eq">${T("fixedPoints")}</label></div>
          <div class="form-check form-switch m-0"><input class="form-check-input" type="checkbox" id="${p}-color-time" checked><label class="form-check-label small" for="${p}-color-time">${T("colorByIter")}</label></div>
        </div>
      </div>
      ${plotCard(`${p}-plot-main`, "plot-tall")}
      <div class="row g-3 mt-0">
        <div class="col-xl-6">${plotCard(`${p}-plot-a`, "plot-sq")}</div>
        <div class="col-xl-6">${plotCard(`${p}-plot-b`, "plot-sq")}</div>
      </div>`;

  const bifForm = ode ? `
      <div class="col-6 col-md-2"><label class="form-label" for="${p}-bif-param">${T("ctrlParam")}</label><select id="${p}-bif-param" class="form-select form-select-sm mono"></select></div>
      <div class="col-6 col-md-1">${numIn(`${p}-bif-min`, "min")}</div>
      <div class="col-6 col-md-1">${numIn(`${p}-bif-max`, "max")}</div>
      <div class="col-6 col-md-1">${numIn(`${p}-bif-steps`, T("steps"), 'min="2" max="2000"')}</div>
      <div class="col-6 col-md-1"><label class="form-label" for="${p}-bif-var">${T("maxVar")}</label><select id="${p}-bif-var" class="form-select form-select-sm mono"></select></div>
      <div class="col-6 col-md-2">${numIn(`${p}-bif-tr`, T("transientDiscard"), 'min="0"')}</div>
      <div class="col-6 col-md-1">${numIn(`${p}-bif-tt`, T("totalT"), 'min="0"')}</div>
      <div class="col-6 col-md-1">${numIn(`${p}-bif-dt`, "Δt (RK4)", 'min="0"')}</div>` : `
      <div class="col-6 col-md-2"><label class="form-label" for="${p}-bif-param">${T("ctrlParam")}</label><select id="${p}-bif-param" class="form-select form-select-sm mono"></select></div>
      <div class="col-6 col-md-1">${numIn(`${p}-bif-min`, "min")}</div>
      <div class="col-6 col-md-1">${numIn(`${p}-bif-max`, "max")}</div>
      <div class="col-6 col-md-1">${numIn(`${p}-bif-steps`, T("steps"), 'min="2" max="3000"')}</div>
      <div class="col-6 col-md-1"><label class="form-label" for="${p}-bif-var">${T("variable")}</label><select id="${p}-bif-var" class="form-select form-select-sm mono"></select></div>
      <div class="col-6 col-md-2">${numIn(`${p}-bif-tr`, T("transientIter"), 'min="0"')}</div>
      <div class="col-6 col-md-2">${numIn(`${p}-bif-keep`, T("keptIter"), 'min="1" max="2000"')}</div>`;

  const pcTab = ode ? `
    <div class="tab-pane fade" id="${p}-tab-pc" role="tabpanel">
      <div class="card-lab">
        <div class="card-head">${T("sectionPlane")} <span data-tex="\\Sigma = \\{\\mathbf{x} : x_k = c\\}"></span></div>
        <form id="${p}-pc-form" class="row g-2 align-items-end" novalidate>
          <div class="col-6 col-md-1"><label class="form-label" for="${p}-pc-var">x<sub>k</sub></label><select id="${p}-pc-var" class="form-select form-select-sm mono"></select></div>
          <div class="col-6 col-md-2"><label class="form-label" for="${p}-pc-val">c</label>
            <div class="input-group input-group-sm"><input id="${p}-pc-val" type="number" step="any" class="form-control mono"><button type="button" class="btn btn-outline-info" id="${p}-pc-mean" data-i18n="useMean" data-i18n-title="useMeanTitle"></button></div></div>
          <div class="col-6 col-md-2"><label class="form-label" for="${p}-pc-dir">${T("crossDir")}</label>
            <select id="${p}-pc-dir" class="form-select form-select-sm"><option value="1" data-i18n="dirUp"></option><option value="-1" data-i18n="dirDown"></option><option value="0" data-i18n="dirBoth"></option></select></div>
          <div class="col-6 col-md-2">${numIn(`${p}-pc-tr`, T("transientDiscard"), 'min="0"')}</div>
          <div class="col-6 col-md-2">${numIn(`${p}-pc-tmax`, T("totalT"), 'min="0"')}</div>
          <div class="col-12 col-md-3"><button type="submit" id="${p}-pc-btn" class="btn btn-analyze btn-sm w-100"><span class="spinner-border spinner-border-sm me-1 d-none" role="status"></span>${T("computeSection")}</button></div>
        </form>
        <div class="detail mt-2" id="${p}-pc-info" data-i18n="pcInfo"></div>
      </div>
      <div class="toolbar mt-3">
        <div class="toolbar-group"><span class="toolbar-label">${T("sectionAxes")}</span>
          <select id="${p}-pc-a" class="form-select form-select-sm axis-select"></select>
          <select id="${p}-pc-b" class="form-select form-select-sm axis-select"></select></div>
        <div class="toolbar-group"><span class="toolbar-label">${T("returnMapVar")}</span>
          <select id="${p}-pc-rm" class="form-select form-select-sm axis-select"></select></div>
        <div class="chips" id="${p}-pc-chips"></div>
      </div>
      <div class="row g-3">
        <div class="col-xl-6">${plotCard(`${p}-plot-pc`, "plot-tall")}</div>
        <div class="col-xl-6">${plotCard(`${p}-plot-pc-rm`, "plot-tall")}</div>
      </div>
    </div>` : "";

  const basinTab = `
    <div class="tab-pane fade" id="${p}-tab-basin" role="tabpanel">
      <div class="card-lab">
        <div class="card-head">${T("basinGrid")}</div>
        <form id="${p}-bs-form" class="row g-2 align-items-end" novalidate>
          <div class="col-6 col-md-1"><label class="form-label" for="${p}-bs-a">${T("axisA")}</label><select id="${p}-bs-a" class="form-select form-select-sm mono"></select></div>
          <div class="col-6 col-md-1">${numIn(`${p}-bs-amin`, "min")}</div>
          <div class="col-6 col-md-1">${numIn(`${p}-bs-amax`, "max")}</div>
          <div class="col-6 col-md-1 need-2"><label class="form-label" for="${p}-bs-b">${T("axisB")}</label><select id="${p}-bs-b" class="form-select form-select-sm mono"></select></div>
          <div class="col-6 col-md-1 need-2">${numIn(`${p}-bs-bmin`, "min")}</div>
          <div class="col-6 col-md-1 need-2">${numIn(`${p}-bs-bmax`, "max")}</div>
          <div class="col-6 col-md-1">${numIn(`${p}-bs-res`, T("resolution"), 'min="10"')}</div>
          ${ode ? `<div class="col-6 col-md-1">${numIn(`${p}-bs-t`, "t", 'min="0"')}</div><div class="col-6 col-md-1">${numIn(`${p}-bs-dt`, "Δt", 'min="0"')}</div>`
          : `<div class="col-6 col-md-1">${numIn(`${p}-bs-n`, T("iterations"), 'min="10"')}</div>`}
          <div class="col-12 col-md-2"><label class="form-label" for="${p}-bs-override">${T("paramOverride")}</label><input id="${p}-bs-override" class="form-control form-control-sm mono" spellcheck="false" placeholder="rho=20"></div>
          <div class="col-12 col-md-1"><button type="submit" id="${p}-bs-btn" class="btn btn-analyze btn-sm w-100"><span class="spinner-border spinner-border-sm me-1 d-none" role="status"></span>${T("compute")}</button></div>
        </form>
        <div class="detail mt-2" id="${p}-bs-info" data-i18n="${ode ? "basinInfoOde" : "basinInfoMap"}"></div>
      </div>
      <div class="row g-3 mt-0">
        <div class="col-xl-8">${plotCard(`${p}-plot-bs`, "plot-xl")}</div>
        <div class="col-xl-4"><div class="card-lab h-100"><div class="card-head">${T("attractors")}</div><div id="${p}-bs-legend" class="detail" data-i18n="waiting"></div></div></div>
      </div>
    </div>`;

  const specTab = `
    <div class="tab-pane fade" id="${p}-tab-spec" role="tabpanel">
      <div class="toolbar">
        <div class="toolbar-group"><span class="toolbar-label">${T("variable")}</span><select id="${p}-sp-var" class="form-select form-select-sm axis-select"></select>
          <div class="form-check form-switch m-0"><input class="form-check-input" type="checkbox" id="${p}-sp-logf"><label class="form-check-label small" for="${p}-sp-logf">${T("logFreq")}</label></div></div>
        <div class="chips" id="${p}-sp-chips"></div>
      </div>
      ${plotCard(`${p}-plot-sp`, "plot-tall", `${T("psdHead")} <span data-tex="S(f)\\;[\\mathrm{dB}]"></span>`)}
      <div class="card-lab mt-3 method-note"><div class="card-head">${T("method")}</div><div class="detail" data-i18n-html="${ode ? "specMethodOde" : "specMethodMap"}"></div></div>
    </div>`;

  const fracTab = `
    <div class="tab-pane fade" id="${p}-tab-frac" role="tabpanel">
      <div class="row g-3">
        <div class="col-xl-4"><div class="card-lab h-100"><div class="card-head">${T("fractalDims")}</div>
          <table class="table table-sm table-lab mb-2"><tbody id="${p}-fd-table"><tr><td class="text-secondary-lab" data-i18n="waiting"></td></tr></tbody></table>
          <div class="detail" id="${p}-fd-note" data-i18n-html="fdNote"></div></div></div>
        <div class="col-xl-8">${plotCard(`${p}-plot-fd-c`, "plot-mid", `${T("corrSum")} <span data-tex="\\ln C(r)\\;\\text{vs}\\;\\ln r"></span>`)}</div>
      </div>
      <div class="row g-3 mt-0">
        <div class="col-xl-6">${plotCard(`${p}-plot-fd-slope`, "plot-mid", `${T("localSlope")} <span data-tex="d\\ln C / d\\ln r"></span>`)}</div>
        <div class="col-xl-6">${plotCard(`${p}-plot-fd-box`, "plot-mid", `${T("boxCount")} <span data-tex="\\ln N(\\varepsilon)\\;\\text{vs}\\;\\ln(1/\\varepsilon)"></span>`)}</div>
      </div>
    </div>`;

  const cmpTab = `
    <div class="tab-pane fade" id="${p}-tab-cmp" role="tabpanel">
      <div class="card-lab">
        <div class="card-head">${T("cmpSelect")}</div>
        <div id="${p}-cmp-list" class="cmp-list"></div>
        <div class="d-flex gap-2 mt-2 flex-wrap">
          <button type="button" class="btn btn-outline-info btn-sm" id="${p}-cmp-all" data-i18n="selectAll"></button>
          <button type="button" class="btn btn-outline-info btn-sm" id="${p}-cmp-none" data-i18n="selectNone"></button>
          <button type="button" id="${p}-cmp-btn" class="btn btn-analyze btn-sm"><span class="spinner-border spinner-border-sm me-1 d-none" role="status"></span>${T("cmpRun")}</button>
        </div>
        <div class="detail mt-2" id="${p}-cmp-info" data-i18n="cmpInfo"></div>
      </div>
      <div class="card-lab mt-3 scroll-x"><table class="table table-sm table-lab mb-0" id="${p}-cmp-table"></table></div>
      <div class="row g-3 mt-0">
        <div class="col-xl-6">${plotCard(`${p}-plot-cmp-l`, "plot-mid")}</div>
        <div class="col-xl-6">${plotCard(`${p}-plot-cmp-d`, "plot-mid")}</div>
      </div>
    </div>`;

  return `
  <div class="app-shell view ${ode ? "" : "d-none"} dim-${ode ? 3 : 2}" id="view-${kind}">
  ${sidebar}
  <main class="main">
    <div id="${p}-alerts"></div>
    ${kpis}
    ${tabNav}
    <div class="tab-content lab-content" id="${p}-content">
      <div class="tab-pane fade show active" id="${p}-tab-phase" role="tabpanel">${phaseTab}</div>
      <div class="tab-pane fade" id="${p}-tab-time" role="tabpanel">
        ${plotCard(`${p}-plot-ts`, "plot-tall", T(ode ? "timeSeries" : "orbitSeries"))}
        <div class="toolbar mt-3">
          <div class="toolbar-group"><span class="toolbar-label">${T("butterflyVar")}</span><select id="${p}-bf-var" class="form-select form-select-sm axis-select"></select></div>
          <div class="chips" id="${p}-bf-chips"></div>
        </div>
        <div class="row g-3">
          <div class="col-xl-6"><div class="card-lab"><div class="card-head" id="${p}-bf-head"></div><div id="${p}-plot-bf" class="plot plot-mid"></div></div></div>
          <div class="col-xl-6">${plotCard(`${p}-plot-bf-ln`, "plot-mid", `${T("separation")} <span data-tex="\\ln\\|\\Delta\\mathbf{x}\\|"></span>`)}</div>
        </div>
      </div>
      <div class="tab-pane fade" id="${p}-tab-eq" role="tabpanel">
        <div class="row g-3">
          <div class="col-xl-6">
            <div class="card-lab"><div class="card-head">${T(ode ? "vectorField" : "mapFunction")} <span data-tex="\\mathbf{F}(\\mathbf{x})"></span></div><div id="${p}-sym-eqs" class="tex-block"></div><div id="${p}-sym-params" class="tex-inline text-secondary-lab"></div></div>
            <div class="card-lab mt-3"><div class="card-head">${T(ode ? "divergence" : "determinant")}</div><div id="${p}-sym-div" class="tex-block"></div><div id="${p}-sym-div-num" class="tex-block"></div><div id="${p}-sym-div-detail" class="detail"></div></div>
          </div>
          <div class="col-xl-6">
            <div class="card-lab"><div class="card-head">${T("symJac")}</div><div id="${p}-sym-jac" class="tex-block scroll-x"></div></div>
            <div class="card-lab mt-3"><div class="card-head">${T("numJac")}</div><div id="${p}-sym-jac-num" class="tex-block scroll-x"></div></div>
          </div>
        </div>
        <div class="card-lab mt-3">
          <div class="card-head d-flex justify-content-between flex-wrap gap-2"><span>${T(ode ? "eqStability" : "fpStability")} <span data-tex="${ode ? "\\mathbf{F}(\\mathbf{x}^*) = 0" : "\\mathbf{F}(\\mathbf{x}^*) = \\mathbf{x}^*"}"></span></span><span class="badge-lab" id="${p}-eq-method">—</span></div>
          <div id="${p}-eq-list" class="eq-list"></div>
        </div>
        ${plotCard(`${p}-plot-eig`, "plot-mid", T(ode ? "eigPlane" : "eigPlaneMap")).replace('class="card-lab"', 'class="card-lab mt-3"')}
      </div>
      <div class="tab-pane fade" id="${p}-tab-lyap" role="tabpanel">
        <div class="row g-3">
          <div class="col-xl-4"><div class="card-lab h-100"><div class="card-head">${T("lyapExps")}</div>
            <table class="table table-sm table-lab mb-2"><tbody id="${p}-lyap-table"><tr><td class="text-secondary-lab" data-i18n="waiting"></td></tr></tbody></table>
            <div id="${p}-lyap-dky" class="tex-block"></div><div id="${p}-lyap-diag" class="detail"></div></div></div>
          <div class="col-xl-8">${plotCard(`${p}-plot-lyap`, "plot-tall", `${T("convergence")} <span data-tex="${ode ? "\\lambda_i(t) = \\frac{1}{t}\\sum \\ln|R_{ii}|" : "\\lambda_i(n) = \\frac{1}{n}\\sum \\ln|R_{ii}|"}"></span>`)}</div>
        </div>
        <div class="card-lab mt-3 method-note"><div class="card-head">${T("method")}</div><div class="detail" data-i18n-html="${ode ? "lyapMethodOde" : "lyapMethodMap"}"></div></div>
      </div>
      <div class="tab-pane fade" id="${p}-tab-bif" role="tabpanel">
        <div class="card-lab">
          <div class="card-head">${T("scanSettings")}</div>
          <form id="${p}-bif-form" class="row g-2 align-items-end" novalidate>
            ${bifForm}
            <div class="col-12 col-md-2"><button type="submit" id="${p}-bif-btn" class="btn btn-analyze btn-sm w-100"><span class="spinner-border spinner-border-sm me-1 d-none" role="status"></span>${T("startScan")}</button></div>
          </form>
          <div class="detail mt-2" id="${p}-bif-info" data-i18n="${ode ? "bifInfoOde" : "bifInfoMap"}"></div>
        </div>
        ${plotCard(`${p}-plot-bif`, "plot-xl").replace('class="card-lab"', 'class="card-lab mt-3"')}
      </div>
      ${pcTab}
      ${basinTab}
      ${specTab}
      ${fracTab}
      ${cmpTab}
    </div>
    <footer class="foot">ChaosLab · FastAPI · NumPy · SciPy · SymPy · Plotly.js · KaTeX · <span data-i18n="offline"></span></footer>
  </main>
  </div>`;
}

/* ================================================================ Lab sınıfı */
class Lab {
  constructor(kind) {
    this.kind = kind;
    this.ode = kind === "ode";
    this.p = this.ode ? "o" : "m";
    this.base = this.ode ? "/api" : "/api/map";
    this.dim = this.ode ? 3 : 2;
    this.presets = {};
    this.result = null;
    this.bif = null;
    this.pc = null;
    this.basin = null;
    this.cmp = null;
    this.initialized = false;
  }
  $(s) { return $(`${this.p}-${s}`); }
  say(id, key, vars, extra) {
    this.msgs = this.msgs || {};
    this.msgs[id] = [key, vars, extra];
    const el = this.$(id);
    el.removeAttribute("data-i18n");
    const fv = vars ? Object.fromEntries(Object.entries(vars).map(([k, v]) => [k, typeof v === "number" && Number.isInteger(v) ? v.toLocaleString(nloc()) : v])) : vars;
    el.textContent = t(key, fv) + (extra ? t(extra[0], extra[1]) : "");
  }
  resay() { Object.entries(this.msgs || {}).forEach(([id, [k, v, e]]) => this.say(id, k, v, e)); }
  vars() { return varNames(this.dim); }

  alert(msg, kind = "error") {
    const box = this.$("alerts");
    const div = document.createElement("div");
    div.className = "alert-lab" + (kind === "warn" ? " warn" : "");
    div.innerHTML = `<div>${escapeHtml(msg)}</div><button type="button" aria-label="×">×</button>`;
    div.querySelector("button").addEventListener("click", () => div.remove());
    box.appendChild(div);
    if (kind === "warn") setTimeout(() => div.remove(), 12000);
  }
  clearAlerts() { this.$("alerts").innerHTML = ""; }

  num(s, name) {
    const el = this.$(s);
    const v = parseFloat(el.value);
    if (!Number.isFinite(v)) { el.classList.add("is-invalid"); throw new Error(t("errNumber", { name })); }
    el.classList.remove("is-invalid");
    return v;
  }

  /* Denklem ve başlangıç koşulu satırlarını N boyuta göre yeniden kurar (girilen değerler korunur). */
  renderRows() {
    this.eqCache = this.eqCache || {};
    this.icCache = this.icCache || {};
    document.querySelectorAll(`#${this.p}-eqs input`).forEach((el) => { this.eqCache[el.dataset.v] = el.value; });
    document.querySelectorAll(`#${this.p}-ics input`).forEach((el) => { this.icCache[el.dataset.v] = el.value; });
    const vars = this.vars();
    const lhs = (v) => (this.ode ? `\\dot{${vtex(v)}} =` : (v.length > 1 ? `${vtex(v)}^{(n+1)} =` : `${v}_{n+1} =`));
    this.$("eqs").innerHTML = vars.map((v) =>
      `<div class="eq-row"><span class="eq-label" data-tex="${lhs(v)}"></span><input id="${this.p}-eq-${v}" data-v="${v}" class="form-control form-control-sm mono" spellcheck="false" value="${escapeHtml(this.eqCache[v] || "")}"></div>`).join("");
    this.$("ics").innerHTML = vars.map((v) =>
      `<div class="input-group input-group-sm"><span class="input-group-text">${v}₀</span><input id="${this.p}-ic-${v}" data-v="${v}" type="number" step="any" class="form-control mono" value="${escapeHtml(this.icCache[v] ?? "0")}"></div>`).join("");
    renderStaticTex(this.$("eqs"));
    this.$("vars-hint").innerHTML = `${t("varsAre")}: <code>${vars.join(", ")}</code>${this.ode ? ", <code>t</code>" : ""}`;
  }

  setDim(dim) {
    dim = Math.max(1, Math.min(MAX_DIM, Math.round(dim) || 1));
    this.dim = dim;
    const view = $(`view-${this.kind}`);
    [1, 2, 3, 4].forEach((d) => view.classList.toggle(`dim-${d}`, d === Math.min(dim, 4)));
    this.$("dim-n").value = dim;
    view.querySelectorAll(".dim-quick").forEach((b) => b.classList.toggle("active", Number(b.dataset.dim) === dim));
    this.renderRows();
    this.fillVarSelectors();
    this.fillBifSelectors();
  }

  paramNames() {
    return this.$("params").value.split(/[,;\n]+/).map((s) => s.split("=")[0].trim()).filter((s) => /^[A-Za-z_]\w*$/.test(s));
  }

  fillVarSelectors(axes) {
    const vars = this.vars();
    const cur = axes || [1, 2, 3].map((i) => this.$(`ax-${i}`).value);
    const defs = [vars[0], vars[1] || vars[0], vars[2] || vars[vars.length - 1]];
    [1, 2, 3].forEach((i) => {
      const v = vars.includes(cur[i - 1]) ? cur[i - 1] : defs[i - 1];
      fillSelect(this.$(`ax-${i}`), vars, v);
    });
    const keep = (id, d) => fillSelect(this.$(id), vars, vars.includes(this.$(id).value) ? this.$(id).value : d);
    keep("bf-var", vars[0]);
    if (!this.ode) keep("rm-var", vars[0]);
    const spv = this.$("sp-var").value;
    fillSelect(this.$("sp-var"), ["__all", ...vars], vars.includes(spv) ? spv : "__all", [t("allVars"), ...vars]);
    keep("bs-a", vars[0]);
    keep("bs-b", vars[1] || vars[0]);
    if (this.ode) {
      keep("pc-var", vars[2] || vars[vars.length - 1]);
      this.fillPcAxes();
    }
  }

  fillPcAxes() {
    const vars = this.vars();
    const others = vars.filter((v) => v !== this.$("pc-var").value);
    const a = this.$("pc-a").value, b = this.$("pc-b").value, r = this.$("pc-rm").value;
    fillSelect(this.$("pc-a"), others, others.includes(a) ? a : others[0]);
    fillSelect(this.$("pc-b"), others, others.includes(b) && b !== this.$("pc-a").value ? b : others[1]);
    fillSelect(this.$("pc-rm"), others, others.includes(r) ? r : others[0]);
  }

  fillBifSelectors(bif) {
    const names = this.paramNames();
    const cur = bif ? bif.param : this.$("bif-param").value;
    fillSelect(this.$("bif-param"), names, names.includes(cur) ? cur : names[0]);
    const vars = this.vars();
    const v = bif ? bif.var : this.$("bif-var").value;
    fillSelect(this.$("bif-var"), vars, vars.includes(v) ? v : vars[0]);
  }

  loadPreset(key) {
    const p = this.presets[key];
    if (!p) return;
    const dim = p.equations.length;
    this.$("params").value = p.params;
    this.setDim(dim);
    varNames(dim).forEach((v, i) => {
      this.$(`eq-${v}`).value = p.equations[i] || "";
      this.$(`ic-${v}`).value = p.initial[i] !== undefined ? p.initial[i] : 0;
    });
    this.$("delta0").value = p.delta0;
    if (this.ode) {
      this.$("t-max").value = p.t_max;
      this.$("dt").value = p.dt;
      this.$("lyap-t").value = p.lyap_t;
      this.$("lyap-dt").value = p.lyap_dt;
      this.$("lyap-tr").value = p.lyap_transient;
    } else {
      this.$("n-iter").value = p.n_iter;
      this.$("transient").value = p.transient;
      this.$("lyap-n").value = p.lyap_n;
    }
    this.fillVarSelectors(p.axes || ["x", "y", "z"]);
    const b = p.bif;
    this.fillBifSelectors(b);
    this.$("bif-min").value = b.min;
    this.$("bif-max").value = b.max;
    this.$("bif-steps").value = b.steps;
    if (this.ode) {
      this.$("bif-tr").value = b.t_transient;
      this.$("bif-tt").value = b.t_total;
      this.$("bif-dt").value = b.dt;
      const pc = p.poincare;
      if (pc) {
        this.$("pc-var").value = pc.var;
        this.$("pc-val").value = pc.value;
        this.$("pc-dir").value = String(pc.dir);
        this.$("pc-tr").value = pc.t_transient;
        this.$("pc-tmax").value = pc.t_max;
        this.fillPcAxes();
      }
    } else {
      this.$("bif-tr").value = b.transient;
      this.$("bif-keep").value = b.keep;
    }
    const bs = p.basin;
    if (bs) {
      this.$("bs-a").value = bs.a;
      if (this.dim > 1) this.$("bs-b").value = bs.b;
      this.$("bs-amin").value = bs.a_range[0];
      this.$("bs-amax").value = bs.a_range[1];
      this.$("bs-bmin").value = bs.b_range[0];
      this.$("bs-bmax").value = bs.b_range[1];
      this.$("bs-res").value = bs.res;
      this.$("bs-override").value = bs.override || "";
      if (this.ode) { this.$("bs-t").value = bs.t; this.$("bs-dt").value = bs.dt; }
      else this.$("bs-n").value = bs.n;
    }
  }

  collectSystem() {
    const equations = this.vars().map((v) => {
      const el = this.$(`eq-${v}`);
      const s = el.value.trim();
      if (!s) { el.classList.add("is-invalid"); throw new Error(t("errEmptyEq", { v })); }
      el.classList.remove("is-invalid");
      return s;
    });
    const initial = this.vars().map((v) => this.num(`ic-${v}`, `${v}₀`));
    return { equations, params: this.$("params").value.trim(), initial };
  }

  /* ------------------------------------------------------------ çalıştırma */
  async runAnalysis(ev) {
    if (ev) ev.preventDefault();
    this.clearAlerts();
    let payload;
    try {
      payload = this.ode ? {
        ...this.collectSystem(),
        t_max: this.num("t-max", "t_max"), dt: this.num("dt", "Δt"), delta0: this.num("delta0", "δ₀"),
        lyap_t: this.num("lyap-t", "Lyapunov T"), lyap_dt: this.num("lyap-dt", "Lyapunov Δt"),
        lyap_transient: this.num("lyap-tr", t("transient")),
        compute_lyapunov: this.$("compute-lyap").checked, method: this.$("method").value,
      } : {
        ...this.collectSystem(),
        n_iter: Math.round(this.num("n-iter", "N")), transient: Math.round(this.num("transient", t("transientIter"))),
        delta0: this.num("delta0", "δ₀"), lyap_n: Math.round(this.num("lyap-n", "Lyapunov N")),
        compute_lyapunov: this.$("compute-lyap").checked,
      };
    } catch (err) { this.alert(err.message); return; }
    const btn = this.$("analyze-btn");
    setBusy(btn, true);
    this.$("status").removeAttribute("data-i18n");
    this.say("status", "statusRunning");
    this.$("content").classList.add("loading-veil");
    try {
      const data = await api(`${this.base}/analyze`, payload);
      this.result = data;
      this.renderAll();
      this.say("status", "statusDone", { s: data.elapsed.toFixed(2), n: data.trajectory.n_points });
      if (data.trajectory.warning) this.alert(trB(data.trajectory.warning), "warn");
    } catch (err) {
      this.alert(err.message);
      this.say("status", "error");
    } finally {
      setBusy(btn, false);
      this.$("content").classList.remove("loading-veil");
    }
  }

  async runBifurcation(ev) {
    if (ev) ev.preventDefault();
    this.clearAlerts();
    let payload;
    try {
      const param = this.$("bif-param").value;
      if (!param) throw new Error(t("errNoParam"));
      payload = {
        ...this.collectSystem(), param,
        p_min: this.num("bif-min", "min"), p_max: this.num("bif-max", "max"),
        steps: Math.round(this.num("bif-steps", t("steps"))), var: this.$("bif-var").value,
      };
      if (this.ode) Object.assign(payload, { t_transient: this.num("bif-tr", t("transient")), t_total: this.num("bif-tt", t("totalT")), dt: this.num("bif-dt", "Δt") });
      else Object.assign(payload, { transient: Math.round(this.num("bif-tr", t("transient"))), keep: Math.round(this.num("bif-keep", t("keptIter"))) });
    } catch (err) { this.alert(err.message); return; }
    setBusy(this.$("bif-btn"), true);
    this.$("bif-info").removeAttribute("data-i18n");
    this.say("bif-info", "scanRunning", { p: payload.param, a: payload.p_min, b: payload.p_max, n: payload.steps });
    try {
      const data = await api(`${this.base}/bifurcation`, payload);
      this.bif = data;
      this.plotBifurcation();
      const div = data.diverged.length ? t("divergedAt", { n: data.diverged.length }) : "";
      this.say("bif-info", "scanDone", { s: data.elapsed.toFixed(2), n: data.n_points }, data.diverged.length ? ["divergedAt", { n: data.diverged.length }] : null);
    } catch (err) {
      this.alert(err.message);
      this.$("bif-info").textContent = `${t("error")} ${err.message}`;
    } finally { setBusy(this.$("bif-btn"), false); }
  }

  async runPoincare(ev) {
    if (ev) ev.preventDefault();
    this.clearAlerts();
    let payload;
    try {
      payload = {
        ...this.collectSystem(),
        plane_var: this.$("pc-var").value, plane_value: this.num("pc-val", "c"),
        direction: parseInt(this.$("pc-dir").value, 10),
        t_transient: this.num("pc-tr", t("transient")), t_max: this.num("pc-tmax", t("totalT")),
      };
    } catch (err) { this.alert(err.message); return; }
    setBusy(this.$("pc-btn"), true);
    this.$("pc-info").removeAttribute("data-i18n");
    this.say("pc-info", "pcRunning");
    try {
      const data = await api("/api/poincare", payload);
      this.pc = data;
      this.fillPcAxes();
      this.plotPoincare();
      this.say("pc-info", "pcDone", { s: data.elapsed.toFixed(2), n: data.n_points });
      if (data.n_points < 3) this.alert(t("pcFew"), "warn");
    } catch (err) {
      this.alert(err.message);
      this.$("pc-info").textContent = `${t("error")} ${err.message}`;
    } finally { setBusy(this.$("pc-btn"), false); }
  }

  async runBasin(ev) {
    if (ev) ev.preventDefault();
    this.clearAlerts();
    let payload;
    try {
      payload = {
        ...this.collectSystem(),
        var_a: this.$("bs-a").value, var_b: this.dim > 1 ? this.$("bs-b").value : this.$("bs-a").value,
        a_min: this.num("bs-amin", "min"), a_max: this.num("bs-amax", "max"),
        b_min: this.dim > 1 ? this.num("bs-bmin", "min") : 0, b_max: this.dim > 1 ? this.num("bs-bmax", "max") : 1,
        res: Math.round(this.num("bs-res", t("resolution"))), override: this.$("bs-override").value.trim(),
      };
      if (this.ode) Object.assign(payload, { t_total: this.num("bs-t", "t"), dt: this.num("bs-dt", "Δt") });
      else payload.n_iter = Math.round(this.num("bs-n", t("iterations")));
    } catch (err) { this.alert(err.message); return; }
    setBusy(this.$("bs-btn"), true);
    const info = this.$("bs-info");
    info.removeAttribute("data-i18n");
    this.say("bs-info", "basinRunning", { n: payload.res * (this.dim > 1 ? payload.res : 1) });
    try {
      const data = await api(`${this.base}/basin`, payload);
      this.basin = data;
      this.plotBasin();
      this.say("bs-info", "basinDone", { s: data.elapsed.toFixed(2), k: data.attractors.length, d: fmt(100 * data.diverged_fraction, 3) });
    } catch (err) {
      this.alert(err.message);
      info.textContent = `${t("error")} ${err.message}`;
    } finally { setBusy(this.$("bs-btn"), false); }
  }

  async runCompare() {
    this.clearAlerts();
    const keys = [...this.$("cmp-list").querySelectorAll("input:checked")].map((c) => c.value);
    if (!keys.length) { this.alert(t("cmpNone")); return; }
    setBusy(this.$("cmp-btn"), true);
    const info = this.$("cmp-info");
    info.removeAttribute("data-i18n");
    this.say("cmp-info", "cmpRunning", { n: keys.length });
    try {
      const data = await api(`${this.base}/compare`, { keys });
      this.cmp = data;
      this.renderCompare();
      this.say("cmp-info", "cmpDone", { s: data.elapsed.toFixed(2), n: data.rows.length });
    } catch (err) {
      this.alert(err.message);
      info.textContent = `${t("error")} ${err.message}`;
    } finally { setBusy(this.$("cmp-btn"), false); }
  }

  /* ------------------------------------------------------------ render */
  rerender() {
    this.resay();
    this.fillVarSelectors();
    if (this.result) this.renderAll();
    if (this.bif) this.plotBifurcation();
    if (this.pc) this.plotPoincare();
    if (this.basin) this.plotBasin();
    if (this.cmp) this.renderCompare();
    this.fillCompareList();
  }

  renderAll() {
    const d = this.result;
    this.renderKPIs();
    this.plotPhase();
    this.plotTimeSeries();
    this.plotButterfly();
    this.renderSymbolic();
    this.renderLyapunov();
    this.plotSpectrum();
    this.renderFractal();
    if (this.ode && !this.$("pc-val").value) this.useMean();
    return d;
  }

  classTone(cls) {
    if (!cls) return "";
    if (cls.startsWith("Hiperkaotik")) return "hyper";
    if (cls.startsWith("Kaotik")) return "chaos";
    if (cls.startsWith("Iraksak") || cls.startsWith("Kararsız")) return "bad";
    if (cls.startsWith("Periyodik") || cls.startsWith("Yarı")) return "info";
    return "good";
  }

  renderKPIs() {
    const d = this.result;
    const s = d.symbolic;
    const P = this.p;
    $(`${P}-kpi-dim`).textContent = `${s.dimension}${t("dimSuffix")}`;
    $(`${P}-kpi-dim`).className = "kpi-value info";
    $(`${P}-kpi-dim-sub`).textContent = `(${s.variables.join(", ")})`;
    const dv = this.ode ? s.divergence : s.determinant;
    if (this.ode) {
      $(`${P}-kpi-2`).textContent = trB(s.autonomy_label);
      $(`${P}-kpi-2`).className = "kpi-value " + (s.autonomous ? "good" : "warn");
      $(`${P}-kpi-2-sub`).textContent = s.autonomous ? t("autoSub") : t("nonAutoSub");
    } else {
      $(`${P}-kpi-2`).textContent = t("mapKind");
      $(`${P}-kpi-2`).className = "kpi-value info";
      $(`${P}-kpi-2-sub`).textContent = `${s.fixed_points.length} ${t("fixedPointsShort")}`;
    }
    const k3 = $(`${P}-kpi-3`);
    k3.textContent = trB(dv.class).split(" (")[0];
    k3.title = trB(dv.class);
    k3.className = "kpi-value " + (dv.class.startsWith("Kayıplı") ? "good" : (dv.class.includes("Korunumlu") || dv.class.includes("Koruyan") || dv.class.startsWith("1B")) ? "info" : "warn");
    const sym = this.ode ? "∇·F" : "|det J|";
    $(`${P}-kpi-3-sub`).textContent = dv.value !== null && dv.value !== undefined
      ? (dv.state_dependent ? `⟨${sym}⟩ = ${fmt(dv.value)}` : `${sym} = ${fmt(dv.value)}`) : t("stateDependent");
    const l = d.lyapunov;
    const kc = $(`${P}-kpi-class`);
    if (l) {
      kc.textContent = trB(l.classification);
      kc.title = trB(l.classification);
      kc.className = "kpi-value " + this.classTone(l.classification);
      $(`${P}-kpi-class-sub`).textContent = l.exponents[0] !== null ? `λ₁ = ${fmt(l.exponents[0], 4)}` : t("lyapFailed");
      $(`${P}-kpi-dky`).textContent = l.kaplan_yorke !== null ? fmt(l.kaplan_yorke, 5) : "—";
      $(`${P}-kpi-dky`).className = "kpi-value hyper";
    } else {
      kc.textContent = "—"; kc.className = "kpi-value";
      $(`${P}-kpi-class-sub`).textContent = t("lyapOff");
      $(`${P}-kpi-dky`).textContent = "—";
    }
    const fr = d.fractal || {};
    const d2 = fr.correlation && fr.correlation.available ? fr.correlation.D2 : null;
    const d0 = fr.box && fr.box.available ? fr.box.D0 : null;
    $(`${P}-kpi-d2`).textContent = d2 !== null ? fmt(d2, 4) : "—";
    $(`${P}-kpi-d2`).className = "kpi-value violet";
    tex($(`${P}-kpi-d2-sub`), `D_2 \\;/\\; D_0 = ${d0 !== null ? fmt(d0, 4) : "—"}`);
  }

  eqPoints() {
    const s = this.result.symbolic;
    return (this.ode ? s.equilibria : s.fixed_points) || [];
  }

  /* ---------------------------------------------------- faz portresi */
  plotPhase() {
    const d = this.result;
    if (!d) return;
    const th = TH();
    const vars = d.variables;
    const st = Object.fromEntries(vars.map((v, i) => [v, d.trajectory.states[i]]));
    const tt = d.trajectory.t;
    const showEq = this.$("show-eq").checked;
    const byTime = this.$("color-time").checked;
    const eqs = this.eqPoints();
    const eqColor = eqs.map((e) => (e.stable ? th.good : th.bad));
    const P = this.p;

    if (this.ode && vars.length < 3) {
      // 1B: x(t) + denge çizgileri; 2B: faz düzlemi
      if (vars.length === 1) {
        const tr = [{ type: "scatter", mode: "lines", name: "x(t)", x: tt, y: st.x, line: { width: 2, color: th.accent } }];
        const shapes = showEq ? eqs.map((e) => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: e.point[0], y1: e.point[0], line: { color: e.stable ? th.good : th.bad, width: 1.5, dash: "dash" } })) : [];
        Plotly.react(`${P}-plot-3d`, tr, baseLayout({ title: ttl(t("phase1d")), xaxis: ax("t"), yaxis: ax("x"), shapes, showlegend: false }), PLOT_CONFIG);
        return;
      }
      const a = this.$("ax-1").value || "x", b = this.$("ax-2").value || "y";
      const tr = [{ type: "scatter", mode: "lines+markers", name: t("trajectory"), x: st[a], y: st[b],
        line: { width: 1.5, color: th.accent }, marker: byTime ? { size: 3, color: tt, colorscale: "Portland", showscale: true, colorbar: { title: { text: "t" }, thickness: 12, tickfont: { size: FS.tick, color: th.tick } } } : { size: 0.1, color: th.accent },
        hovertemplate: `${a}=%{x:.4f}<br>${b}=%{y:.4f}<extra></extra>` }];
      if (showEq && eqs.length) tr.push({ type: "scatter", mode: "markers", name: t("equilibria"), x: eqs.map((e) => e.point[vars.indexOf(a)]), y: eqs.map((e) => e.point[vars.indexOf(b)]),
        marker: { size: 11, symbol: "diamond", color: eqColor, line: { color: th.title, width: 1 } }, text: eqs.map((e) => trB(e.type)), hovertemplate: "%{text}<extra></extra>" });
      Plotly.react(`${P}-plot-3d`, tr, baseLayout({ title: ttl(`${t("phasePlane")} (${a}, ${b})`), xaxis: ax(a), yaxis: ax(b), showlegend: false }), PLOT_CONFIG);
      return;
    }
    if (this.ode) {
      const axes = [1, 2, 3].map((i) => this.$(`ax-${i}`).value).map((a) => (vars.includes(a) ? a : vars[0]));
      const traces = [{
        type: "scatter3d", mode: "lines", name: t("trajectory"),
        x: st[axes[0]], y: st[axes[1]], z: st[axes[2]],
        line: byTime
          ? { width: 2.2, color: tt, colorscale: "Portland", showscale: true, colorbar: { title: { text: "t" }, thickness: 12, len: 0.6, tickfont: { color: th.tick, size: FS.tick } } }
          : { width: 2.2, color: th.accent },
        hovertemplate: `${axes[0]}=%{x:.4f}<br>${axes[1]}=%{y:.4f}<br>${axes[2]}=%{z:.4f}<extra></extra>`,
      }];
      if (showEq && eqs.length) {
        const idx = axes.map((a) => vars.indexOf(a));
        traces.push({
          type: "scatter3d", mode: "markers", name: t("equilibria"),
          x: eqs.map((e) => e.point[idx[0]]), y: eqs.map((e) => e.point[idx[1]]), z: eqs.map((e) => e.point[idx[2]]),
          marker: { size: 5, color: eqColor, symbol: "diamond", line: { color: th.title, width: 1 } },
          text: eqs.map((e) => trB(e.type)), hovertemplate: "%{text}<br>(%{x:.4f}, %{y:.4f}, %{z:.4f})<extra></extra>",
        });
      }
      Plotly.react(`${P}-plot-3d`, traces, baseLayout({
        title: ttl(`${t("phase3d")} (${axes.join(" – ")})`),
        margin: { l: 0, r: 0, t: 44, b: 0 }, showlegend: showEq && eqs.length > 0, legend: { x: 0.01, y: 0.98 },
        scene: { xaxis: sceneAxis(axes[0]), yaxis: sceneAxis(axes[1]), zaxis: sceneAxis(axes[2]), aspectmode: "cube", camera: { eye: { x: 1.5, y: 1.5, z: 0.9 } } },
        uirevision: axes.join(""),
      }), PLOT_CONFIG);
      const pairs = [[axes[0], axes[1]], [axes[0], axes[2]], [axes[1], axes[2]]];
      pairs.forEach(([a, b], i) => {
        const tr = [{
          type: "scatter", mode: "lines", x: st[a], y: st[b],
          line: { width: 1, color: [th.c[a], th.c[b], th.amber][i] },
          hovertemplate: `${a}=%{x:.4f}<br>${b}=%{y:.4f}<extra></extra>`,
        }];
        if (showEq && eqs.length) {
          tr.push({ type: "scatter", mode: "markers", x: eqs.map((e) => e.point[vars.indexOf(a)]), y: eqs.map((e) => e.point[vars.indexOf(b)]),
            marker: { size: 9, symbol: "diamond", color: eqColor, line: { color: th.title, width: 1 } }, hoverinfo: "skip" });
        }
        Plotly.react(`${P}-plot-p${i + 1}`, tr, baseLayout({
          title: ttl(`${a.toUpperCase()}${b.toUpperCase()} ${t("projection")}`), xaxis: ax(a), yaxis: ax(b), showlegend: false,
        }), PLOT_CONFIG);
      });
      return;
    }

    // ---- ayrık harita
    const n0 = Math.min(d.trajectory.transient || 0, Math.floor(tt.length / 2));
    const post = (arr) => arr.slice(n0);
    const nIter = post(tt);
    const mk = (extra = {}) => ({ size: vars.length > 1 ? 2.5 : 4, opacity: 0.8, ...extra });
    const colorMarker = byTime ? { color: nIter, colorscale: "Viridis", showscale: false } : { color: th.accent };
    if (this.dim === 1) {
      const xs = st.x;
      const cw = { x: [], y: [] };
      const nc = Math.min(xs.length - 1, 150);
      cw.x.push(xs[0]); cw.y.push(xs[0]);
      for (let i = 0; i < nc; i++) {
        cw.x.push(xs[i]); cw.y.push(xs[i + 1]);
        cw.x.push(xs[i + 1]); cw.y.push(xs[i + 1]);
      }
      const c = d.curve || { x: [], y: [] };
      const lo = Math.min(...c.x), hi = Math.max(...c.x);
      const tr = [
        { type: "scatter", mode: "lines", name: "f(x)", x: c.x, y: c.y, line: { width: 2.5, color: th.c.y } },
        { type: "scatter", mode: "lines", name: "y = x", x: [lo, hi], y: [lo, hi], line: { width: 1.5, color: th.faint, dash: "dash" } },
        { type: "scatter", mode: "lines", name: t("cobweb"), x: cw.x, y: cw.y, line: { width: 1, color: th.pink } },
        { type: "scatter", mode: "markers", name: "x₀", x: [xs[0]], y: [xs[0]], marker: { size: 10, color: th.amber, symbol: "star" } },
      ];
      if (showEq && eqs.length) tr.push({ type: "scatter", mode: "markers", name: t("fixedPoints"), x: eqs.map((e) => e.point[0]), y: eqs.map((e) => e.point[0]),
        marker: { size: 11, symbol: "diamond", color: eqColor, line: { color: th.title, width: 1 } }, text: eqs.map((e) => trB(e.type)), hovertemplate: "%{text}<br>x*=%{x:.6f}<extra></extra>" });
      Plotly.react(`${P}-plot-main`, tr, baseLayout({ title: ttl(t("cobwebTitle")), xaxis: ax("x<sub>n</sub>"), yaxis: ax("x<sub>n+1</sub>", { scaleanchor: "x", scaleratio: 1 }), legend: { x: 0.01, y: 0.99 } }), PLOT_CONFIG);
    } else if (this.dim === 2) {
      const a = this.$("ax-1").value, b = this.$("ax-2").value;
      const tr = [{ type: "scattergl", mode: "markers", name: t("orbit"), x: post(st[a]), y: post(st[b]), marker: mk(colorMarker),
        hovertemplate: `${a}=%{x:.5f}<br>${b}=%{y:.5f}<extra></extra>` }];
      if (showEq && eqs.length) tr.push({ type: "scatter", mode: "markers", name: t("fixedPoints"), x: eqs.map((e) => e.point[vars.indexOf(a)]), y: eqs.map((e) => e.point[vars.indexOf(b)]),
        marker: { size: 11, symbol: "diamond", color: eqColor, line: { color: th.title, width: 1 } }, text: eqs.map((e) => trB(e.type)), hovertemplate: "%{text}<extra></extra>" });
      Plotly.react(`${P}-plot-main`, tr, baseLayout({ title: ttl(`${t("attractor")} (${a}, ${b})`), xaxis: ax(a), yaxis: ax(b), showlegend: showEq && eqs.length > 0, legend: { x: 0.01, y: 0.99 } }), PLOT_CONFIG);
    } else {
      const axes = [1, 2, 3].map((i) => this.$(`ax-${i}`).value);
      const tr = [{ type: "scatter3d", mode: "markers", name: t("orbit"), x: post(st[axes[0]]), y: post(st[axes[1]]), z: post(st[axes[2]]),
        marker: { size: 1.6, opacity: 0.8, ...colorMarker } }];
      if (showEq && eqs.length) {
        const idx = axes.map((q) => vars.indexOf(q));
        tr.push({ type: "scatter3d", mode: "markers", name: t("fixedPoints"), x: eqs.map((e) => e.point[idx[0]]), y: eqs.map((e) => e.point[idx[1]]), z: eqs.map((e) => e.point[idx[2]]),
          marker: { size: 5, color: eqColor, symbol: "diamond" }, text: eqs.map((e) => trB(e.type)), hovertemplate: "%{text}<extra></extra>" });
      }
      Plotly.react(`${P}-plot-main`, tr, baseLayout({ title: ttl(`${t("attractor")} (${axes.join(", ")})`), margin: { l: 0, r: 0, t: 44, b: 0 }, showlegend: false,
        scene: { xaxis: sceneAxis(axes[0]), yaxis: sceneAxis(axes[1]), zaxis: sceneAxis(axes[2]), aspectmode: "cube" }, uirevision: axes.join("") }), PLOT_CONFIG);
    }
    // dönüş haritası
    const rv = this.$("rm-var").value || "x";
    const s = post(st[rv]);
    Plotly.react(`${P}-plot-a`, [{ type: "scattergl", mode: "markers", x: s.slice(0, -1), y: s.slice(1), marker: { size: 3, color: th.c[rv] || th.accent, opacity: 0.8 },
      hovertemplate: `${rv}ₙ=%{x:.5f}<br>${rv}ₙ₊₁=%{y:.5f}<extra></extra>` }],
    baseLayout({ title: ttl(`${t("returnMap")} ${rv}<sub>n</sub> → ${rv}<sub>n+1</sub>`), xaxis: ax(`${rv}<sub>n</sub>`), yaxis: ax(`${rv}<sub>n+1</sub>`), showlegend: false }), PLOT_CONFIG);
    // değişmez yoğunluk (histogram)
    Plotly.react(`${P}-plot-b`, [{ type: "histogram", x: s, nbinsx: 120, histnorm: "probability density", marker: { color: th.c[rv] || th.accent, opacity: 0.85 } }],
      baseLayout({ title: ttl(`${t("invDensity")} ρ(${rv})`), xaxis: ax(rv), yaxis: ax("ρ"), showlegend: false, bargap: 0 }), PLOT_CONFIG);
  }

  plotTimeSeries() {
    const d = this.result;
    const th = TH();
    const vars = d.variables;
    const n = vars.length;
    const many = d.trajectory.t.length > 600;
    const traces = vars.map((v, i) => ({
      type: this.ode ? "scatter" : "scattergl",
      mode: this.ode ? "lines" : (many ? "markers" : "lines+markers"),
      name: this.ode ? `${v}(t)` : `${v}ₙ`,
      x: d.trajectory.t, y: d.trajectory.states[i],
      xaxis: "x", yaxis: i === 0 ? "y" : `y${i + 1}`,
      line: { width: this.ode ? 1.3 : 0.8, color: th.c[v] }, marker: { size: many ? 2 : 4, color: th.c[v] },
    }));
    const layout = baseLayout({
      grid: { rows: n, columns: 1, pattern: "coupled", roworder: "top to bottom" },
      margin: { l: 76, r: 20, t: 20, b: 60 }, showlegend: true, legend: { orientation: "h", y: 1.05, x: 0 },
      xaxis: ax(this.ode ? "t" : "n"),
    });
    vars.forEach((v, i) => { layout[i === 0 ? "yaxis" : `yaxis${i + 1}`] = deepMerge(axisStyle(), { title: { text: this.ode ? `${v}(t)` : `${v}<sub>n</sub>` } }); });
    // N büyükse her alt grafik okunabilir kalsın diye yüksekliği büyüt
    this.$("plot-ts").style.height = `${Math.max(580, 150 * n)}px`;
    Plotly.react(`${this.p}-plot-ts`, traces, layout, PLOT_CONFIG);
  }

  plotButterfly() {
    const d = this.result;
    if (!d) return;
    const th = TH();
    const b = d.butterfly;
    const v = this.$("bf-var").value || "x";
    const i = Math.max(0, d.variables.indexOf(v));
    const tl = this.ode ? "t" : "n";
    this.$("bf-head").textContent = t("bfHead", { v, d: fmt(b.delta0) });
    const mode = this.ode ? "lines" : "lines";
    Plotly.react(`${this.p}-plot-bf`, [
      { type: "scatter", mode, name: `${v} · x₀`, x: b.t, y: b.base[i], line: { width: 1.4, color: th.accent } },
      { type: "scatter", mode, name: `${v} · x₀+δ₀`, x: b.t, y: b.perturbed[i], line: { width: 1.4, color: th.pink, dash: "dot" } },
    ], baseLayout({ xaxis: ax(tl), yaxis: ax(this.ode ? `${v}(t)` : `${v}<sub>n</sub>`), legend: { orientation: "h", y: 1.14, x: 0 }, margin: { t: 36 } }), PLOT_CONFIG);

    const traces = [{ type: "scatter", mode: "lines", name: "ln‖Δx‖", x: b.t, y: b.ln_distance, line: { width: 1.4, color: th.amber } }];
    if (b.lambda_estimate !== null && b.lambda_estimate !== undefined && b.t.length) {
      const ln0 = Math.log(b.delta0);
      const tEnd = b.t[b.t.length - 1];
      const lnMax = Math.max(...b.ln_distance.filter((x) => x !== null));
      const tSat = Math.min(tEnd, (lnMax - ln0) / Math.max(b.lambda_estimate, 1e-9));
      traces.push({ type: "scatter", mode: "lines", name: `${t("slope")} ≈ λ₁ = ${fmt(b.lambda_estimate, 4)}`, x: [0, tSat], y: [ln0, ln0 + b.lambda_estimate * tSat], line: { width: 1.8, color: th.violet, dash: "dash" } });
    }
    Plotly.react(`${this.p}-plot-bf-ln`, traces, baseLayout({ xaxis: ax(tl), yaxis: ax("ln‖Δx‖"), legend: { orientation: "h", y: 1.14, x: 0 }, margin: { t: 36 } }), PLOT_CONFIG);
    const chips = [`<span class="chip">δ₀ = ${fmt(b.delta0)}</span>`];
    if (b.lambda_estimate !== null) chips.push(`<span class="chip violet">${t("lambdaFit")} ≈ ${fmt(b.lambda_estimate, 4)}</span>`);
    if (b.predictability_horizon !== null) chips.push(`<span class="chip amber">${t("horizon")} : ${tl} ≈ ${fmt(b.predictability_horizon, 4)}</span>`);
    this.$("bf-chips").innerHTML = chips.join("");
  }

  renderSymbolic() {
    const s = this.result.symbolic;
    tex(this.$("sym-eqs"), String.raw`\begin{aligned}` + s.equations_latex.map((e) => e.replace(" = ", " &= ")).join(String.raw`\\`) + String.raw`\end{aligned}`, true);
    if (s.params_latex) tex(this.$("sym-params"), s.params_latex, false); else this.$("sym-params").textContent = t("noParams");
    const dv = this.ode ? s.divergence : s.determinant;
    tex(this.$("sym-div"), trB(dv.symbolic_latex), true);
    tex(this.$("sym-div-num"), trB(dv.numeric_latex), true);
    this.$("sym-div-detail").innerHTML = `<strong>${escapeHtml(trB(dv.class))}</strong> — ${escapeHtml(trB(dv.detail))}`;
    tex(this.$("sym-jac"), s.jacobian_latex, true);
    tex(this.$("sym-jac-num"), s.jacobian_numeric_latex, true);
    const eqs = this.eqPoints();
    const method = this.ode ? s.equilibria_method : s.fixed_points_method;
    this.$("eq-method").textContent = trB(method);
    const host = this.$("eq-list");
    host.innerHTML = "";
    if (!eqs.length) host.innerHTML = `<div class="detail">${escapeHtml(t("noEq"))} ${escapeHtml(trB(method))}</div>`;
    eqs.forEach((e, k) => {
      const nonhyp = e.type.startsWith("Hiperbolik Değil");
      const cls = nonhyp ? "" : e.stable ? "stable" : "unstable";
      const div = document.createElement("div");
      div.className = `eq-item ${cls}`;
      div.innerHTML = `
        <div class="eq-title"><span>E<sub>${k}</sub></span><span class="eq-type ${nonhyp ? "nonhyp" : cls}">${escapeHtml(trB(e.type))}</span></div>
        <div class="tex-block pt"></div><div class="tex-block ev"></div>
        <details><summary>J(x*)</summary><div class="tex-block jm"></div></details>`;
      host.appendChild(div);
      tex(div.querySelector(".pt"), `E_{${k}} = ${e.latex}`, false);
      tex(div.querySelector(".ev"), e.eigen_latex, false);
      tex(div.querySelector(".jm"), `J(E_{${k}}) = ${e.jacobian_latex}`, true);
    });
    this.plotEigen(eqs);
  }

  plotEigen(eqs) {
    const th = TH();
    const traces = eqs.map((e, k) => ({
      type: "scatter", mode: "markers", name: `E${k}`,
      x: e.eigenvalues.map((v) => v.re), y: e.eigenvalues.map((v) => v.im),
      marker: { size: 12, color: th.pal[k % th.pal.length], symbol: "x-thin", line: { width: 3, color: th.pal[k % th.pal.length] } },
      hovertemplate: `E${k}: %{x:.5f} %{y:+.5f}i<extra></extra>`,
    }));
    const extra = this.ode
      ? { xaxis: ax("Re(λ)", { zeroline: true, zerolinecolor: th.bad, zerolinewidth: 2 }), yaxis: ax("Im(λ)", { zeroline: true }),
          annotations: [{ xref: "paper", yref: "paper", x: 0.99, y: 0.98, xanchor: "right", text: t("eigHintOde"), showarrow: false, font: { size: 13, color: th.tick } }] }
      : { xaxis: ax("Re(λ)", { zeroline: true }), yaxis: ax("Im(λ)", { zeroline: true, scaleanchor: "x", scaleratio: 1 }),
          shapes: [{ type: "circle", xref: "x", yref: "y", x0: -1, y0: -1, x1: 1, y1: 1, line: { color: th.bad, width: 2, dash: "dot" } }],
          annotations: [{ xref: "paper", yref: "paper", x: 0.99, y: 0.98, xanchor: "right", text: t("eigHintMap"), showarrow: false, font: { size: 13, color: th.tick } }] };
    Plotly.react(`${this.p}-plot-eig`, traces, baseLayout({ showlegend: eqs.length <= 24, ...extra }), PLOT_CONFIG);
  }

  renderLyapunov() {
    const l = this.result.lyapunov;
    const table = this.$("lyap-table");
    if (!l || l.diverged) {
      table.innerHTML = `<tr><td class="text-secondary-lab">${t(l ? "lyapDiverged" : "lyapOff")}</td></tr>`;
      this.$("lyap-dky").innerHTML = "";
      this.$("lyap-diag").innerHTML = l ? `<strong>${escapeHtml(trB(l.classification))}</strong>` : "";
      Plotly.purge(`${this.p}-plot-lyap`);
      return;
    }
    const th = TH();
    const tol = l.zero_tolerance;
    const rows = l.exponents.map((v, i) => {
      const c = Math.abs(v) <= tol ? "zero" : v > 0 ? "pos" : "neg";
      return `<tr><td><span class="lt" data-i="${i + 1}"></span></td><td class="${c} text-end">${v.toFixed(6)}</td></tr>`;
    });
    rows.push(`<tr><td><span class="lsum"></span></td><td class="text-end">${l.sum.toFixed(6)}</td></tr>`);
    if (l.divergence_check !== null && l.divergence_check !== undefined) {
      rows.push(`<tr><td><span class="ldiv"></span></td><td class="text-end text-secondary-lab">${fmt(l.divergence_check, 6)}</td></tr>`);
    }
    if (!this.ode && this.result.symbolic.determinant.value !== null && this.dim > 1) {
      rows.push(`<tr><td><span class="ldet"></span></td><td class="text-end text-secondary-lab">${fmt(Math.log(Math.abs(this.result.symbolic.determinant.value)), 6)}</td></tr>`);
    }
    table.innerHTML = rows.join("");
    table.querySelectorAll(".lt").forEach((el) => tex(el, `\\lambda_{${el.dataset.i}}`));
    const ls = table.querySelector(".lsum"); if (ls) tex(ls, String.raw`\sum_i \lambda_i`);
    const ld = table.querySelector(".ldiv"); if (ld) tex(ld, String.raw`\langle \nabla\cdot\mathbf{F} \rangle`);
    const lj = table.querySelector(".ldet"); if (lj) tex(lj, String.raw`\langle \ln|\det J| \rangle`);
    const lam = l.exponents;
    let cum = 0, j = 0;
    for (let i = 0; i < lam.length; i++) { if (cum + lam[i] >= 0) { cum += lam[i]; j = i + 1; } else break; }
    let ky;
    if (j === 0) ky = String.raw`D_{KY} = 0`;
    else if (j >= lam.length) ky = String.raw`D_{KY} = ${lam.length}`;
    else {
      const sumTerms = lam.slice(0, j).map((v) => v.toFixed(4)).join(" + ").replace(/\+ -/g, "- ");
      ky = String.raw`D_{KY} = j + \frac{\sum_{i=1}^{j}\lambda_i}{|\lambda_{j+1}|} = ${j} + \frac{${sumTerms}}{|${lam[j].toFixed(4)}|} = ${l.kaplan_yorke.toFixed(5)}`;
    }
    tex(this.$("lyap-dky"), ky, true);
    this.$("lyap-diag").innerHTML = `${t("diagnosis")}: <strong>${escapeHtml(trB(l.classification))}</strong><br>
      ${t("zeroTol")} |λ| ≤ ${fmt(tol, 3)} · ${this.ode ? `T = ${fmt(l.t_total)} · Δt = ${fmt(l.dt)}` : `N = ${l.t_total}`}<br>${t(this.ode ? "lyapCheckOde" : "lyapCheckMap")}`;
    const traces = l.history.map((h, i) => ({
      type: "scatter", mode: "lines", name: `λ${i + 1} → ${lam[i].toFixed(4)}`,
      x: l.time, y: h, line: { width: 1.8, color: i < 4 ? [th.pink, th.amber, th.accent, th.c.w][i] : th.pal[i % th.pal.length] },
    }));
    Plotly.react(`${this.p}-plot-lyap`, traces, baseLayout({
      xaxis: ax(this.ode ? "t" : "n"), yaxis: ax("λ<sub>i</sub>", { zeroline: true, zerolinecolor: th.faint, zerolinewidth: 2 }),
      legend: { orientation: "h", y: 1.1, x: 0 }, margin: { t: 36 },
    }), PLOT_CONFIG);
  }

  plotBifurcation() {
    const b = this.bif;
    const th = TH();
    const pts = {
      type: "scattergl", mode: "markers", name: this.ode ? t("localMax") : `${b.var}<sub>n</sub>`,
      x: b.p, y: b.maxima,
      marker: { size: this.ode ? 2 : 1.6, color: b.maxima, colorscale: [[0, th.accent], [0.5, th.violet], [1, th.pink]], opacity: 0.75 },
      hovertemplate: `${b.param}=%{x:.5f}<br>${b.var}=%{y:.5f}<extra></extra>`,
    };
    if (this.ode || !b.lambda_max) {
      Plotly.react(`${this.p}-plot-bif`, [pts], baseLayout({
        title: ttl(this.ode ? `${t("bifTitle")} — ${b.var}<sub>max</sub> vs ${b.param}` : `${t("orbitDiagTitle")} — ${b.var} vs ${b.param}`),
        xaxis: ax(b.param), yaxis: ax(this.ode ? `${b.var} ${t("localMaxima")}` : b.var), showlegend: false,
      }), PLOT_CONFIG);
      return;
    }
    const lam = { type: "scatter", mode: "lines", name: "λ<sub>max</sub>", x: b.p_values, y: b.lambda_max, xaxis: "x", yaxis: "y2", line: { width: 1.4, color: th.amber } };
    const L = baseLayout({
      title: ttl(`${t("orbitDiagTitle")} — ${b.var} vs ${b.param}`),
      grid: { rows: 2, columns: 1, pattern: "coupled", roworder: "top to bottom" },
      xaxis: ax(b.param), yaxis: ax(b.var, { domain: [0.34, 1] }),
      showlegend: false,
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y2", y0: 0, y1: 0, line: { color: th.bad, width: 1.5, dash: "dot" } }],
    });
    L.yaxis2 = deepMerge(axisStyle(), { title: { text: "λ<sub>max</sub>" }, domain: [0, 0.28] });
    L.yaxis.domain = [0.34, 1];
    Plotly.react(`${this.p}-plot-bif`, [pts, lam], L, PLOT_CONFIG);
  }

  useMean() {
    if (!this.result) return;
    const v = this.$("pc-var").value;
    const i = this.result.variables.indexOf(v);
    const arr = (this.result.trajectory.states[i] || []).filter((x) => x !== null);
    const tail = arr.slice(Math.floor(arr.length / 5));
    if (!tail.length) return;
    const m = tail.reduce((a, b) => a + b, 0) / tail.length;
    this.$("pc-val").value = Number(m.toPrecision(6));
  }

  plotPoincare() {
    const d = this.pc;
    if (!d) return;
    const th = TH();
    const a = this.$("pc-a").value, b = this.$("pc-b").value, r = this.$("pc-rm").value;
    const single = (d.others || []).length < 2 || a === b;
    const pb = d.points[single ? a : b] || [];
    const pa = single ? pb.map((_, k) => k) : (d.points[a] || []);
    Plotly.react(`${this.p}-plot-pc`, [{
      type: "scattergl", mode: "markers", x: pa, y: pb,
      marker: { size: 3.5, color: d.t, colorscale: "Viridis", showscale: true, colorbar: { title: { text: "t" }, thickness: 12, tickfont: { size: FS.tick, color: th.tick } } },
      hovertemplate: `${a}=%{x:.5f}<br>${b}=%{y:.5f}<extra></extra>`,
    }], baseLayout({ title: ttl(`${t("poincareTitle")} ${d.plane_var} = ${fmt(d.plane_value)}`), xaxis: ax(single ? "k" : a), yaxis: ax(single ? a : b), showlegend: false }), PLOT_CONFIG);
    const s = d.points[r] || [];
    const lo = Math.min(...s.filter((x) => x !== null)), hi = Math.max(...s.filter((x) => x !== null));
    Plotly.react(`${this.p}-plot-pc-rm`, [
      { type: "scattergl", mode: "markers", x: s.slice(0, -1), y: s.slice(1), marker: { size: 4, color: th.c[r] || th.accent },
        hovertemplate: `${r}ₖ=%{x:.5f}<br>${r}ₖ₊₁=%{y:.5f}<extra></extra>` },
      { type: "scatter", mode: "lines", x: [lo, hi], y: [lo, hi], line: { color: th.faint, dash: "dash", width: 1.5 }, hoverinfo: "skip" },
    ], baseLayout({ title: ttl(`${t("firstReturn")} ${r}<sub>k</sub> → ${r}<sub>k+1</sub>`), xaxis: ax(`${r}<sub>k</sub>`), yaxis: ax(`${r}<sub>k+1</sub>`), showlegend: false }), PLOT_CONFIG);
    const dirTxt = { 1: t("dirUp"), "-1": t("dirDown"), 0: t("dirBoth") }[d.direction];
    const chips = [`<span class="chip">${t("crossings")}: ${d.n_points}</span>`, `<span class="chip violet">${dirTxt}</span>`];
    if (d.mean_return_time !== null) chips.push(`<span class="chip amber">⟨T<sub>ret</sub>⟩ ≈ ${fmt(d.mean_return_time, 4)}</span>`);
    this.$("pc-chips").innerHTML = chips.join("");
  }

  plotBasin() {
    const d = this.basin;
    if (!d) return;
    const th = TH();
    const K = d.attractors.length;
    const colors = [cssVar("--basin-unres"), cssVar("--basin-div"), ...th.pal.concat(th.pal).slice(0, Math.max(1, K + 2))];
    const z = d.labels.map((row) => row.map((v) => v + 2));
    const nC = K + 2;
    const cs = [];
    for (let i = 0; i < nC; i++) {
      cs.push([i / nC, colors[i]]);
      cs.push([(i + 1) / nC, colors[i]]);
    }
    const names = [t("unresolved"), t("divergedLbl"), ...d.attractors.map((a, k) => `A${k + 1}`)];
    const traces = [{
      type: "heatmap", x: d.a, y: d.var_b ? d.b : [0], z, zmin: -0.5 + 0.5, zmax: nC, colorscale: cs, showscale: false,
      text: d.labels.map((row) => row.map((v) => names[v + 2])),
      hovertemplate: `${d.var_a}=%{x:.4f}${d.var_b ? `<br>${d.var_b}=%{y:.4f}` : ""}<br>%{text}<extra></extra>`,
    }];
    // kararlı denge noktaları
    if (d.equilibria && d.var_b) {
      const vars = this.vars();
      const ia = vars.indexOf(d.var_a), ib = vars.indexOf(d.var_b);
      const eqs = d.equilibria.filter((e) => e.point[ia] >= d.a[0] && e.point[ia] <= d.a[d.a.length - 1] && e.point[ib] >= d.b[0] && e.point[ib] <= d.b[d.b.length - 1]);
      if (eqs.length) traces.push({ type: "scatter", mode: "markers", x: eqs.map((e) => e.point[ia]), y: eqs.map((e) => e.point[ib]),
        marker: { size: 11, symbol: "diamond", color: eqs.map((e) => (e.stable ? th.good : th.bad)), line: { color: "#fff", width: 1.5 } },
        text: eqs.map((e) => trB(e.type)), hovertemplate: "%{text}<extra></extra>" });
    }
    Plotly.react(`${this.p}-plot-bs`, traces, baseLayout({
      title: ttl(`${t("basinTitle")} (${d.var_a}${d.var_b ? `, ${d.var_b}` : ""})`),
      xaxis: ax(`${d.var_a}₀`), yaxis: d.var_b ? ax(`${d.var_b}₀`) : ax("", { showticklabels: false }), showlegend: false,
    }), PLOT_CONFIG);
    // açıklama listesi
    const vars = this.vars();
    const items = d.attractors.map((a, k) => {
      const kind = a.equilibrium !== null && a.equilibrium !== undefined
        ? `${t("stableEq")} E<sub>${a.equilibrium}</sub>` : a.kind === "fixed" ? t("fixedAttr") : t("oscAttr");
      const c = a.center.map((v, i) => `${vars[i]}≈${fmt(v, 4)}`).join(", ");
      return `<div class="bs-item"><span class="sw" style="background:${colors[k + 2]}"></span><div><strong>A${k + 1}</strong> · ${kind} · ${fmt(100 * a.fraction, 3)}%<br><span class="mono small">⟨x⟩: ${c}</span></div></div>`;
    });
    if (d.diverged_fraction > 0) items.push(`<div class="bs-item"><span class="sw" style="background:${colors[1]}"></span><div>${t("divergedLbl")} · ${fmt(100 * d.diverged_fraction, 3)}%</div></div>`);
    const params = Object.entries(d.params_used || {}).map(([k, v]) => `${k}=${fmt(v)}`).join(", ");
    items.push(`<div class="small mt-2">${t("paramsUsed")}: <span class="mono">${escapeHtml(params || "—")}</span></div>`);
    const L = this.$("bs-legend");
    L.removeAttribute("data-i18n");
    L.innerHTML = items.join("");
  }

  plotSpectrum() {
    const s = this.result.spectrum;
    const th = TH();
    const host = `${this.p}-plot-sp`;
    if (!s || !s.available) { Plotly.purge(host); this.$("sp-chips").innerHTML = `<span class="chip">${t("specNA")}</span>`; return; }
    const sel = this.$("sp-var").value;
    const vars = sel === "__all" ? this.result.variables : [sel];
    const logf = this.$("sp-logf").checked;
    const f = s.freq;
    const start = logf ? 1 : 0;
    const traces = vars.map((v) => ({ type: "scatter", mode: "lines", name: v, x: f.slice(start), y: s.vars[v].psd_db.slice(start), line: { width: 1.5, color: th.c[v] } }));
    vars.forEach((v) => {
      const fd = s.vars[v].dominant_freq;
      if (fd) traces.push({ type: "scatter", mode: "markers", showlegend: false, x: [fd], y: [s.vars[v].psd_db[f.indexOf(fd)] ?? null], marker: { size: 11, color: th.c[v], symbol: "triangle-down" }, hovertemplate: `f* = %{x:.5f}<extra>${v}</extra>` });
    });
    Plotly.react(host, traces, baseLayout({
      xaxis: ax(this.ode ? t("freqOde") : t("freqMap"), { type: logf ? "log" : "linear" }), yaxis: ax(t("psdDb")),
      legend: { orientation: "h", y: 1.08, x: 0 }, margin: { t: 36 },
    }), PLOT_CONFIG);
    const chips = vars.map((v) => {
      const q = s.vars[v];
      const H = q.spectral_entropy;
      const tone = H > 0.55 ? "amber" : H > 0.35 ? "violet" : "";
      return `<span class="chip">${v}: f* = ${fmt(q.dominant_freq, 4)}${q.dominant_period ? ` · T* = ${fmt(q.dominant_period, 4)}` : ""}</span><span class="chip ${tone}">H<sub>${v}</sub> = ${fmt(H, 3)}</span>`;
    });
    this.$("sp-chips").innerHTML = chips.join("");
  }

  renderFractal() {
    const fr = this.result.fractal;
    const th = TH();
    const c = fr.correlation, b = fr.box;
    const ky = fr.kaplan_yorke;
    const rows = [];
    rows.push(`<tr><td>${t("corrDim")} <span class="tx" data-t="D_2"></span></td><td class="text-end pos">${c.available ? fmt(c.D2, 4) : "—"}</td><td class="text-end text-secondary-lab small">${c.available ? `R²=${fmt(c.r2, 4)}` : t("reason_" + c.reason)}</td></tr>`);
    rows.push(`<tr><td>${t("boxDim")} <span class="tx" data-t="D_0"></span></td><td class="text-end zero">${b.available ? fmt(b.D0, 4) : "—"}</td><td class="text-end text-secondary-lab small">${b.available ? `R²=${fmt(b.r2, 4)}` : t("reason_" + b.reason)}</td></tr>`);
    rows.push(`<tr><td>${t("kyDim")} <span class="tx" data-t="D_{KY}"></span></td><td class="text-end neg">${ky !== null && ky !== undefined ? fmt(ky, 4) : "—"}</td><td class="text-end text-secondary-lab small">Lyapunov</td></tr>`);
    if (c.available) rows.push(`<tr><td colspan="3" class="text-secondary-lab small">N = ${c.n_points} · Theiler w = ${c.theiler}</td></tr>`);
    const tb = this.$("fd-table");
    tb.innerHTML = rows.join("");
    tb.querySelectorAll(".tx").forEach((el) => tex(el, el.dataset.t));
    if (c.available) {
      const xs = c.log_r, ys = c.log_C;
      const fx = xs.filter((_, i) => c.fit_mask[i]);
      Plotly.react(`${this.p}-plot-fd-c`, [
        { type: "scatter", mode: "markers+lines", name: "ln C(r)", x: xs, y: ys, line: { width: 1, color: th.faint }, marker: { size: 7, color: c.fit_mask.map((m) => (m ? th.pink : th.faint)) } },
        { type: "scatter", mode: "lines", name: `${t("fit")}: D₂ = ${fmt(c.D2, 4)}`, x: [fx[0], fx[fx.length - 1]], y: [c.D2 * fx[0] + c.fit_intercept, c.D2 * fx[fx.length - 1] + c.fit_intercept], line: { width: 3, color: th.violet, dash: "dash" } },
      ], baseLayout({ xaxis: ax("ln r"), yaxis: ax("ln C(r)"), legend: { x: 0.01, y: 0.99 } }), PLOT_CONFIG);
      const lines = [{ type: "scatter", mode: "lines+markers", name: "d ln C / d ln r", x: xs, y: c.local_slope, line: { width: 1.8, color: th.accent }, marker: { size: 5 } }];
      const hl = (y, name, color) => ({ type: "scatter", mode: "lines", name, x: [xs[0], xs[xs.length - 1]], y: [y, y], line: { width: 1.6, color, dash: "dot" } });
      lines.push(hl(c.D2, `D₂ = ${fmt(c.D2, 4)}`, th.pink));
      if (ky !== null && ky !== undefined) lines.push(hl(ky, `D_KY = ${fmt(ky, 4)}`, th.violet));
      Plotly.react(`${this.p}-plot-fd-slope`, lines, baseLayout({ xaxis: ax("ln r"), yaxis: ax(t("localSlopeAx")), legend: { orientation: "h", y: 1.12, x: 0 }, margin: { t: 36 } }), PLOT_CONFIG);
    } else { Plotly.purge(`${this.p}-plot-fd-c`); Plotly.purge(`${this.p}-plot-fd-slope`); }
    if (b.available) {
      const xs = b.log_inv_eps, ys = b.log_N;
      const fx = xs.filter((_, i) => b.fit_mask[i]);
      Plotly.react(`${this.p}-plot-fd-box`, [
        { type: "scatter", mode: "markers+lines", name: "ln N(ε)", x: xs, y: ys, line: { width: 1, color: th.faint }, marker: { size: 8, color: b.fit_mask.map((m) => (m ? th.amber : th.faint)) } },
        { type: "scatter", mode: "lines", name: `${t("fit")}: D₀ = ${fmt(b.D0, 4)}`, x: [fx[0], fx[fx.length - 1]], y: [b.D0 * fx[0] + b.fit_intercept, b.D0 * fx[fx.length - 1] + b.fit_intercept], line: { width: 3, color: th.violet, dash: "dash" } },
      ], baseLayout({ xaxis: ax("ln(1/ε)"), yaxis: ax("ln N(ε)"), legend: { x: 0.01, y: 0.99 } }), PLOT_CONFIG);
    } else Plotly.purge(`${this.p}-plot-fd-box`);
  }

  fillCompareList() {
    const host = this.$("cmp-list");
    const prev = new Set([...host.querySelectorAll("input:checked")].map((c) => c.value));
    const first = host.children.length === 0;
    host.innerHTML = Object.entries(this.presets).map(([k, p]) => {
      const checked = first ? ["lorenz", "rossler", "chen", "logistic", "henon", "ikeda"].includes(k) : prev.has(k);
      return `<label class="cmp-item"><input type="checkbox" class="form-check-input" value="${escapeHtml(k)}" ${checked ? "checked" : ""}> ${escapeHtml(trB(p.name))}</label>`;
    }).join("");
  }

  renderCompare() {
    const rows = this.cmp.rows;
    const th = TH();
    const head = `<thead><tr><th>${t("system")}</th><th>${t("dimShort")}</th><th class="text-end">λ₁</th><th>λ</th><th class="text-end">Σλ</th><th class="text-end">D<sub>KY</sub></th><th class="text-end">D₂</th><th class="text-end">D₀</th><th class="text-end">H<sub>spec</sub></th><th>${t("classCol")}</th></tr></thead>`;
    const body = rows.map((r) => r.ok ? `<tr><td>${escapeHtml(trB(r.name))}</td><td>${r.dim}</td>
      <td class="text-end ${r.lambda_max > 0 ? "pos" : "neg"}">${fmt(r.lambda_max, 4)}</td><td class="small">${r.exponents.map((v) => fmt(v, 3)).join(", ")}</td>
      <td class="text-end">${fmt(r.sum, 4)}</td><td class="text-end">${fmt(r.kaplan_yorke, 4)}</td><td class="text-end">${fmt(r.D2, 4)}</td><td class="text-end">${fmt(r.D0, 4)}</td>
      <td class="text-end">${fmt(r.spectral_entropy, 3)}</td><td><span class="kpi-value ${this.classTone(r.classification)} small-class">${escapeHtml(trB(r.classification))}</span></td></tr>`
      : `<tr><td>${escapeHtml(trB(r.name))}</td><td colspan="9" class="text-danger">${escapeHtml(trB(r.error))}</td></tr>`).join("");
    this.$("cmp-table").innerHTML = head + `<tbody>${body}</tbody>`;
    const ok = rows.filter((r) => r.ok);
    const names = ok.map((r) => trB(r.name).replace(/\s*\(.*\)$/, ""));
    Plotly.react(`${this.p}-plot-cmp-l`, [{ type: "bar", x: names, y: ok.map((r) => r.lambda_max), marker: { color: ok.map((r) => (r.lambda_max > 0 ? th.pink : th.accent)) }, text: ok.map((r) => fmt(r.lambda_max, 3)), textposition: "outside" }],
      baseLayout({ title: ttl(t("cmpLambda")), yaxis: ax("λ<sub>max</sub>"), xaxis: { tickangle: -25 }, showlegend: false, margin: { b: 110 } }), PLOT_CONFIG);
    Plotly.react(`${this.p}-plot-cmp-d`, [
      { type: "bar", name: "D<sub>KY</sub>", x: names, y: ok.map((r) => r.kaplan_yorke), marker: { color: th.violet } },
      { type: "bar", name: "D₂", x: names, y: ok.map((r) => r.D2), marker: { color: th.pink } },
      { type: "bar", name: "D₀", x: names, y: ok.map((r) => r.D0), marker: { color: th.amber } },
    ], baseLayout({ title: ttl(t("cmpDims")), barmode: "group", yaxis: ax(t("dimension")), xaxis: { tickangle: -25 }, legend: { orientation: "h", y: 1.1, x: 0 }, margin: { b: 110, t: 60 } }), PLOT_CONFIG);
  }

  /* ------------------------------------------------------------ başlatma */
  async init() {
    if (this.initialized) return;
    this.initialized = true;
    try {
      this.presets = await api(`${this.base}/presets`);
    } catch (err) { this.alert(`${t("presetsFailed")}: ${err.message}`); return; }
    const sel = this.$("preset");
    Object.entries(this.presets).forEach(([key, p]) => {
      const opt = document.createElement("option");
      opt.value = key;
      opt.dataset.name = p.name;
      opt.textContent = trB(p.name);
      sel.appendChild(opt);
    });
    const first = this.ode ? "lorenz" : "henon";
    sel.value = first;
    this.loadPreset(first);
    this.fillCompareList();

    sel.addEventListener("change", () => { if (sel.value !== "custom") this.loadPreset(sel.value); });
    const changeDim = (n) => { this.setDim(n); sel.value = "custom"; };
    $(`view-${this.kind}`).querySelectorAll(".dim-quick").forEach((b) => b.addEventListener("click", () => changeDim(Number(b.dataset.dim))));
    this.$("dim-n").addEventListener("change", () => changeDim(parseInt(this.$("dim-n").value, 10)));
    this.$("eqs").addEventListener("input", () => { if (sel.value !== "custom") sel.value = "custom"; });
    this.$("params").addEventListener("input", () => {
      if (sel.value !== "custom") sel.value = "custom";
      this.fillBifSelectors();
    });
    ["ax-1", "ax-2", "ax-3", "color-time", "show-eq", ...(this.ode ? [] : ["rm-var"])].forEach((id) => this.$(id).addEventListener("change", () => this.plotPhase()));
    this.$("bf-var").addEventListener("change", () => this.plotButterfly());
    ["sp-var", "sp-logf"].forEach((id) => this.$(id).addEventListener("change", () => { if (this.result) this.plotSpectrum(); }));
    this.$("form").addEventListener("submit", (e) => this.runAnalysis(e));
    this.$("bif-form").addEventListener("submit", (e) => this.runBifurcation(e));
    this.$("bs-form").addEventListener("submit", (e) => this.runBasin(e));
    this.$("cmp-btn").addEventListener("click", () => this.runCompare());
    this.$("cmp-all").addEventListener("click", () => this.$("cmp-list").querySelectorAll("input").forEach((c) => { c.checked = true; }));
    this.$("cmp-none").addEventListener("click", () => this.$("cmp-list").querySelectorAll("input").forEach((c) => { c.checked = false; }));
    if (this.ode) {
      this.$("pc-form").addEventListener("submit", (e) => this.runPoincare(e));
      this.$("pc-mean").addEventListener("click", () => this.useMean());
      this.$("pc-var").addEventListener("change", () => this.fillPcAxes());
      ["pc-a", "pc-b", "pc-rm"].forEach((id) => this.$(id).addEventListener("change", () => this.plotPoincare()));
    }
    document.querySelectorAll(`#view-${this.kind} button[data-bs-toggle="tab"]`).forEach((b) => b.addEventListener("shown.bs.tab", resizeVisiblePlots));
    this.runAnalysis();
  }
}

/* ================================================================ uygulama */
const LABS = {};

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.setAttribute("data-bs-theme", theme);
  $("theme-btn").textContent = theme === "dark" ? "☀" : "☾";
  try { localStorage.setItem("chaoslab-theme", theme); } catch (e) { /* yok say */ }
}

function applyLang(lang) {
  I18N.lang = lang;
  document.documentElement.lang = lang;
  $("lang-btn").textContent = lang === "tr" ? "EN" : "TR";
  try { localStorage.setItem("chaoslab-lang", lang); } catch (e) { /* yok say */ }
  applyI18n(document);
  document.title = t("pageTitle");
  Object.values(LABS).forEach((lab) => {
    lab.$("preset").querySelectorAll("option[data-name]").forEach((o) => { o.textContent = trB(o.dataset.name); });
  });
}

function showMode(mode) {
  ["ode", "map"].forEach((k) => {
    $(`view-${k}`).classList.toggle("d-none", k !== mode);
    $(`mode-${k}`).classList.toggle("active", k === mode);
  });
  try { localStorage.setItem("chaoslab-mode", mode); } catch (e) { /* yok say */ }
  LABS[mode].init().then(() => setTimeout(resizeVisiblePlots, 50));
  setTimeout(resizeVisiblePlots, 50);
}

function boot() {
  $("views").innerHTML = buildView("ode") + buildView("map");
  LABS.ode = new Lab("ode");
  LABS.map = new Lab("map");
  let theme = "dark", lang = "tr", mode = "ode";
  try {
    theme = localStorage.getItem("chaoslab-theme") || theme;
    lang = localStorage.getItem("chaoslab-lang") || lang;
    mode = localStorage.getItem("chaoslab-mode") || mode;
  } catch (e) { /* yok say */ }
  applyTheme(theme);
  applyLang(lang);
  renderStaticTex();
  $("theme-btn").addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    Object.values(LABS).forEach((l) => { if (l.initialized) l.rerender(); });
  });
  $("lang-btn").addEventListener("click", () => {
    applyLang(I18N.lang === "tr" ? "en" : "tr");
    Object.values(LABS).forEach((l) => { if (l.initialized) l.rerender(); });
  });
  $("mode-ode").addEventListener("click", () => showMode("ode"));
  $("mode-map").addEventListener("click", () => showMode("map"));
  window.addEventListener("resize", resizeVisiblePlots);
  showMode(mode === "map" ? "map" : "ode");
}

document.addEventListener("DOMContentLoaded", boot);
