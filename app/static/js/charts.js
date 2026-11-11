// Chart.js builders (vendored UMD build, global Chart). Colors mirror the tokens in input.css.
import { prefersReducedMotion } from "./dom.js";
import { longDate, moneyExact, pct, shortDate } from "./format.js";

export const PALETTE = {
  ink: "#1c1c1a",
  ink2: "#55534d",
  ink3: "#6b6862",
  line: "#e4e2dc",
  data: "#41618c",
  dataBand: "rgba(65, 97, 140, 0.18)",
  dataOuterBand: "rgba(65, 97, 140, 0.08)",
  before: "#8f8a7f",
  beforeBand: "rgba(143, 138, 127, 0.16)",
  beforeOuterBand: "rgba(143, 138, 127, 0.07)",
  whatIf: "#1c1c1a",
  whatIfBand: "rgba(28, 28, 26, 0.10)",
  risk: "#b3261e",
  riskBand: "rgba(179, 38, 30, 0.10)",
  lowPath: "rgba(179, 38, 30, 0.55)",
};

const FONT = { family: '"IBM Plex Sans", system-ui, sans-serif', size: 12 };
const ANIMATION_MS = 650;

function chartLib() {
  if (!window.Chart) throw new Error("Chart library failed to load.");
  const C = window.Chart;
  C.defaults.font = { ...C.defaults.font, ...FONT };
  C.defaults.color = PALETTE.ink2;
  return C;
}

const toDollars = (arr) => arr.map((c) => (c === null || c === undefined ? null : c / 100));

const wholeDollars = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

/** Chart money (axes, labels): whole dollars with thousands separators, e.g. $1,500,000. */
function compactDollars(value) {
  const sign = value < 0 ? "−" : "";
  return `${sign}$${wholeDollars.format(Math.round(Math.abs(value)))}`;
}

/** Pointwise 1st-99th percentile band, drawn first so it sits behind the 10th-90th band. */
function outerBand(label, series, { outerFill, hidden = false }) {
  if (!outerFill || !series.p1 || !series.p99) return [];
  return [
    { label: `${label} P99`, data: toDollars(series.p99), borderWidth: 0, pointRadius: 0, fill: "+1", backgroundColor: outerFill, hidden, role: "outer" },
    { label: `${label} P1`, data: toDollars(series.p1), borderWidth: 0, pointRadius: 0, fill: false, hidden, role: "outer" },
  ];
}

function band(label, series, style) {
  const { line, fill, dash = [], width = 2, hidden = false } = style;
  return [
    ...outerBand(label, series, style),
    { label: `${label} P90`, data: toDollars(series.p90), borderWidth: 0, pointRadius: 0, fill: "+1", backgroundColor: fill, hidden, role: "band" },
    { label: `${label} P10`, data: toDollars(series.p10), borderWidth: 0, pointRadius: 0, fill: false, hidden, role: "band" },
    { label: `${label} P50`, data: toDollars(series.p50), borderColor: line, borderWidth: width, borderDash: dash, pointRadius: 0, fill: false, hidden, role: "median" },
  ];
}

/** Text labels and reference lines drawn on the canvas (no plugin dependency). */
const referencePlugin = {
  id: "tempoReference",
  afterDatasetsDraw(chart, _args, opts) {
    const { ctx, chartArea, scales } = chart;
    if (!opts || !scales.y) return;
    ctx.save();
    ctx.font = `500 11px ${FONT.family}`;
    (opts.hLabels || []).forEach(({ value, text, color }) => {
      const y = scales.y.getPixelForValue(value);
      ctx.fillStyle = color;
      ctx.textAlign = "right";
      ctx.fillText(text, chartArea.right - 4, y - 5);
    });
    (opts.vLines || []).forEach(({ index, text, color }) => {
      const x = scales.x.getPixelForValue(index);
      ctx.strokeStyle = color;
      ctx.setLineDash([2, 3]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.textAlign = x > chartArea.right - 140 ? "right" : "left";
      ctx.fillText(text, x + (ctx.textAlign === "left" ? 4 : -4), chartArea.top + 11);
    });
    ctx.restore();
  },
};

function markerDataset(dates, markers, series) {
  const index = new Map(dates.map((d, i) => [d, i]));
  const data = dates.map(() => null);
  const meta = dates.map(() => []);
  markers.forEach((m) => {
    const i = index.get(m.date);
    if (i === undefined) return;
    data[i] = series.p50[i] / 100;
    meta[i].push(m);
  });
  return {
    label: "Large payments",
    data,
    markerMeta: meta,
    showLine: false,
    pointStyle: "triangle",
    rotation: 180,
    pointRadius: data.map((v) => (v === null ? 0 : 6)),
    pointHoverRadius: 8,
    pointBackgroundColor: PALETTE.ink,
    pointBorderColor: "#fff",
    pointBorderWidth: 1,
    role: "markers",
  };
}

function tooltipLabel(item) {
  const ds = item.dataset;
  if (ds.role === "markers") {
    return (ds.markerMeta[item.dataIndex] || []).map((m) => `${m.vendor}: ${moneyExact(m.amount_cents)} payment`);
  }
  if (ds.role === "buffer") return `Buffer: ${moneyExact(Math.round(item.raw * 100))}`;
  return `${ds.label}: ${moneyExact(Math.round(item.raw * 100))}`;
}

/**
 * Fan chart: pointwise P10-P90 band of end-of-day cash, P50 line, dashed buffer line.
 * series = [{key, label, data:{p10,p50,p90}, style}], markers optional.
 */
export function fanChart(canvas, { dates, series, bufferCents, markers = [], worst = null, lowPaths = [], lowPathsLabel = "Tempo plan" }) {
  const Chart = chartLib();
  const datasets = series.flatMap((s) => band(s.label, s.data, s.style));
  lowPaths.forEach((p, i) => {
    datasets.push({
      label: `${lowPathsLabel}, low scenario ${i + 1}`,
      data: toDollars(p.path),
      borderColor: PALETTE.lowPath,
      borderWidth: 1,
      pointRadius: 0,
      fill: false,
      role: "scenario",
    });
  });
  datasets.push({
    label: "Buffer",
    data: dates.map(() => bufferCents / 100),
    borderColor: PALETTE.ink3,
    borderDash: [6, 4],
    borderWidth: 1.5,
    pointRadius: 0,
    fill: false,
    role: "buffer",
  });
  const primary = series.find((s) => !s.style.hidden) ?? series[0];
  if (markers.length) datasets.push(markerDataset(dates, markers, primary.data));

  const vLines = worst ? [{ index: dates.indexOf(worst.date), text: worst.text, color: PALETTE.ink2 }] : [];
  // Keep the axis on the bands and the buffer: the lowest scenarios can fall far below them; their lines are
  // clipped at the bottom edge and the legend states how low the lowest one goes.
  const bandLows = series.filter((s) => !s.style.hidden).flatMap((s) => (s.data.p1 ?? s.data.p10).map((c) => c / 100));
  const floor = Math.min(bufferCents / 100, ...bandLows);
  const yMin = lowPaths.length ? (floor > 0 ? 0 : Math.floor((floor * 1.25) / 100_000) * 100_000) : undefined;
  return new Chart(canvas, {
    type: "line",
    data: { labels: dates, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: prefersReducedMotion() ? false : { duration: ANIMATION_MS, easing: "easeOutCubic" },
      interaction: { mode: "index", intersect: false },
      layout: { padding: { top: 4, right: 8 } },
      scales: {
        x: {
          grid: { display: false },
          border: { color: PALETTE.line },
          ticks: {
            autoSkip: false,
            maxRotation: 0,
            callback: (_v, i) => (i % 14 === 0 ? shortDate(dates[i]) : ""),
          },
        },
        y: {
          min: yMin,
          grid: { color: PALETTE.line },
          border: { display: false },
          ticks: { callback: (v) => compactDollars(v), maxTicksLimit: 7 },
        },
      },
      plugins: {
        legend: { display: false },
        tempoReference: {
          hLabels: [{ value: bufferCents / 100, text: `Buffer ${compactDollars(bufferCents / 100)}`, color: PALETTE.ink2 }],
          vLines,
        },
        tooltip: {
          backgroundColor: PALETTE.ink,
          titleFont: { ...FONT, weight: "600" },
          bodyFont: FONT,
          padding: 10,
          boxPadding: 4,
          filter: (item) => !item.dataset.hidden && item.raw !== null && !["band", "outer", "scenario"].includes(item.dataset.role),
          callbacks: { title: (items) => longDate(dates[items[0].dataIndex]), label: tooltipLabel },
        },
      },
    },
    plugins: [referencePlugin],
  });
}

/** Set each dataset's visibility from visibleFn(dataset) without rebuilding the chart. */
export function applyVisibility(chart, visibleFn, { animate = true } = {}) {
  chart.data.datasets.forEach((ds) => {
    const visible = visibleFn(ds);
    if (visible !== undefined) ds.hidden = !visible;
  });
  chart.update(animate && !prefersReducedMotion() ? undefined : "none");
}

/** Replace one series' data in place so Chart.js animates the band moving. */
export function updateSeries(chart, label, data) {
  const map = { P90: data.p90, P10: data.p10, P50: data.p50 };
  chart.data.datasets.forEach((ds) => {
    const suffix = ds.label.slice(label.length + 1);
    if (ds.label.startsWith(`${label} `) && map[suffix]) {
      ds.data = toDollars(map[suffix]);
      ds.hidden = false;
    }
  });
  chart.update(prefersReducedMotion() ? "none" : undefined);
}

const errorBarPlugin = {
  id: "tempoErrorBars",
  afterDatasetsDraw(chart, _args, opts) {
    if (!opts?.uppers) return;
    const { ctx, scales } = chart;
    const meta = chart.getDatasetMeta(0);
    ctx.save();
    ctx.strokeStyle = PALETTE.ink;
    ctx.lineWidth = 1.5;
    meta.data.forEach((bar, i) => {
      const upper = opts.uppers[i];
      const y = scales.y.getPixelForValue(upper * 100);
      const half = Math.min(10, bar.width / 3);
      ctx.beginPath();
      ctx.moveTo(bar.x, bar.y);
      ctx.lineTo(bar.x, y);
      ctx.moveTo(bar.x - half, y);
      ctx.lineTo(bar.x + half, y);
      ctx.stroke();
    });
    const target = scales.y.getPixelForValue(opts.target * 100);
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = PALETTE.ink3;
    ctx.beginPath();
    ctx.moveTo(chart.chartArea.left, target);
    ctx.lineTo(chart.chartArea.right, target);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = PALETTE.ink2;
    ctx.font = `500 11px ${FONT.family}`;
    ctx.textAlign = "right";
    ctx.fillText(`Target ${pct(opts.target, 0)}`, chart.chartArea.right - 2, target - 5);
    ctx.restore();
  },
};

const frontierPlugin = {
  id: "tempoFrontier",
  afterDatasetsDraw(chart, _args, opts) {
    if (!opts) return;
    const { ctx, chartArea, scales } = chart;
    ctx.save();
    ctx.font = `500 11px ${FONT.family}`;
    (opts.bars || []).forEach(({ x0, x1, y, color }) => {
      const px0 = scales.x.getPixelForValue(x0);
      const px1 = scales.x.getPixelForValue(x1);
      const py = scales.y.getPixelForValue(y);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(px0, py);
      ctx.lineTo(px1, py);
      ctx.moveTo(px1, py - 4);
      ctx.lineTo(px1, py + 4);
      ctx.stroke();
    });
    (opts.labels || []).forEach(({ x, y, text, below = false }) => {
      const px = scales.x.getPixelForValue(x);
      const py = scales.y.getPixelForValue(y);
      ctx.fillStyle = PALETTE.ink;
      ctx.textAlign = px > chartArea.right - 150 ? "right" : "left";
      ctx.fillText(text, px + (ctx.textAlign === "left" ? 8 : -8), below ? py + 16 : py - 8);
    });
    if (opts.target !== undefined) {
      const x = scales.x.getPixelForValue(opts.target);
      ctx.strokeStyle = PALETTE.ink3;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = PALETTE.ink2;
      ctx.textAlign = "left";
      ctx.fillText(`Target ${opts.target}%`, x + 4, chartArea.top + 11);
    }
    ctx.restore();
  },
};

/**
 * Risk-vs-value frontier: Tempo certified at several targets (line + points), each point's one-sided 95% bound
 * as a horizontal bar, and every baseline as a labeled point. x = seed-C breach rate (%), y = value ($).
 */
export function frontierChart(canvas, { points, baselines, target, names }) {
  const Chart = chartLib();
  const tempo = points.map((p) => ({ x: p.breach_rate * 100, y: p.value_cents / 100, eps: p.epsilon, upper: p.breach_upper }));
  const base = baselines.map((b) => ({ x: b.breach_rate * 100, y: b.value_cents / 100, name: names[b.policy] ?? b.policy, upper: b.breach_upper }));
  const maxX = Math.max(target * 100, ...points.map((p) => p.breach_upper * 100), ...baselines.map((b) => b.breach_upper * 100));
  return new Chart(canvas, {
    type: "scatter",
    data: {
      datasets: [
        { label: "Tempo", data: tempo, showLine: true, borderColor: PALETTE.data, backgroundColor: PALETTE.data, pointRadius: 4, pointHoverRadius: 6, borderWidth: 2 },
        { label: "Baselines", data: base, showLine: false, backgroundColor: PALETTE.before, borderColor: "#fff", borderWidth: 1, pointRadius: 5, pointStyle: "rectRot" },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: prefersReducedMotion() ? false : { duration: 400 },
      layout: { padding: { top: 6, right: 12 } },
      scales: {
        x: {
          min: 0,
          suggestedMax: Math.ceil(maxX + 1),
          title: { display: true, text: "Chance of any buffer breach in 13 weeks (seed C)", color: PALETTE.ink2 },
          grid: { color: PALETTE.line },
          ticks: { callback: (v) => `${v}%` },
        },
        y: {
          title: { display: true, text: "Value vs paying on due dates", color: PALETTE.ink2 },
          grid: { color: PALETTE.line },
          border: { display: false },
          ticks: { callback: (v) => compactDollars(v), maxTicksLimit: 6 },
        },
      },
      plugins: {
        legend: { display: false },
        tempoFrontier: {
          target: target * 100,
          bars: [
            ...tempo.map((p) => ({ x0: p.x, x1: p.upper * 100, y: p.y, color: PALETTE.data })),
            ...base.map((p) => ({ x0: p.x, x1: p.upper * 100, y: p.y, color: PALETTE.before })),
          ],
          labels: [
            ...tempo.map((p) => ({ x: p.x, y: p.y, below: true, text: pct(p.eps, (p.eps * 100) % 1 ? 1 : 0) })),
            ...base.map((p) => ({ x: p.x, y: p.y, text: p.name })),
          ],
        },
        tooltip: {
          backgroundColor: PALETTE.ink,
          callbacks: {
            label: (item) => {
              const p = item.raw;
              const who = p.name ?? `Tempo certified at ${pct(p.eps, 1)}`;
              return [`${who}: ${moneyExact(Math.round(p.y * 100))}`, `Breach ${pct(p.x / 100)}, 95% bound ${pct(p.upper)}`];
            },
          },
        },
      },
    },
    plugins: [frontierPlugin],
  });
}

/** Out-of-sample breach rate per policy with the one-sided 95% upper bound as an error tick. */
export function breachChart(canvas, { labels, rates, uppers, target, highlight }) {
  const Chart = chartLib();
  const colors = uppers.map((u, i) => (u > target ? PALETTE.risk : i === highlight ? PALETTE.data : PALETTE.before));
  const maxPct = Math.max(target, ...uppers) * 100;
  return new Chart(canvas, {
    type: "bar",
    data: { labels, datasets: [{ label: "Breach rate", data: rates.map((r) => r * 100), backgroundColor: colors, borderRadius: 2, maxBarThickness: 44 }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: prefersReducedMotion() ? false : { duration: 400 },
      scales: {
        x: { grid: { display: false }, border: { color: PALETTE.line }, ticks: { color: PALETTE.ink, maxRotation: 0, autoSkip: false } },
        y: {
          beginAtZero: true,
          suggestedMax: Math.ceil(maxPct + 1),
          grid: { color: PALETTE.line },
          border: { display: false },
          ticks: { callback: (v) => `${v}%` },
        },
      },
      plugins: {
        legend: { display: false },
        tempoErrorBars: { uppers, target },
        tooltip: {
          backgroundColor: PALETTE.ink,
          callbacks: {
            label: (item) => [`Breach rate: ${pct(rates[item.dataIndex])}`, `95% upper bound: ${pct(uppers[item.dataIndex])}`],
          },
        },
      },
    },
    plugins: [errorBarPlugin],
  });
}
