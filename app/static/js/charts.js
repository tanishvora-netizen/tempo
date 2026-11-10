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

function compactDollars(value) {
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}$${Math.round(abs / 1_000)}K`;
  return `${sign}$${Math.round(abs)}`;
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
export function fanChart(canvas, { dates, series, bufferCents, markers = [], worst = null }) {
  const Chart = chartLib();
  const datasets = series.flatMap((s) => band(s.label, s.data, s.style));
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
          filter: (item) => !item.dataset.hidden && item.raw !== null && item.dataset.role !== "band" && item.dataset.role !== "outer",
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
