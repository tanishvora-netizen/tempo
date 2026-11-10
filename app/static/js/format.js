// Formatting. Money arrives as integer cents; nothing here invents or rounds data
// beyond display precision. Dates are ISO strings (YYYY-MM-DD) in the company's calendar.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const SMALL_AMOUNT_CENTS = 10_000; // below $100, show cents
const MINUS = "−";

const whole = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const cents2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Table money: $1,234 (no decimals) unless the absolute amount is under $100. */
export function money(centsValue, { signed = false } = {}) {
  if (centsValue === null || centsValue === undefined) return "—";
  const abs = Math.abs(centsValue);
  const body = abs < SMALL_AMOUNT_CENTS && abs !== 0 ? cents2.format(abs / 100) : whole.format(Math.round(abs / 100));
  const sign = centsValue < 0 ? MINUS : signed && centsValue > 0 ? "+" : "";
  return `${sign}$${body}`;
}

/** Exact money with cents, for tooltips: $48,750.14 */
export function moneyExact(centsValue) {
  if (centsValue === null || centsValue === undefined) return "—";
  const sign = centsValue < 0 ? MINUS : "";
  return `${sign}$${cents2.format(Math.abs(centsValue) / 100)}`;
}

/** KPI money: $48.8K, $1.48M. Use with a tooltip carrying moneyExact. */
export function moneyShort(centsValue, { signed = false } = {}) {
  if (centsValue === null || centsValue === undefined) return "—";
  const dollars = Math.abs(centsValue) / 100;
  const sign = centsValue < 0 ? MINUS : signed && centsValue > 0 ? "+" : "";
  if (dollars >= 1_000_000) return `${sign}$${(dollars / 1_000_000).toFixed(2)}M`;
  if (dollars >= 10_000) return `${sign}$${(dollars / 1_000).toFixed(1).replace(/\.0$/, "")}K`;
  return `${sign}$${whole.format(Math.round(dollars))}`;
}

/** Percent from a fraction: 0.0244 -> "2.44%". */
export function pct(fraction, digits = 2) {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return "—";
  return `${(fraction * 100).toFixed(digits)}%`;
}

/** Annual rate from a fraction: 0.3724 -> "37.2%/yr". */
export function perYear(fraction, digits = 1) {
  if (fraction === null || fraction === undefined) return "—";
  return `${(fraction * 100).toFixed(digits)}%/yr`;
}

export function count(n) {
  return n === null || n === undefined ? "—" : whole.format(n);
}

function parts(iso) {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return { y, m, d };
}

/** "Nov 21" */
export function shortDate(iso) {
  if (!iso) return "—";
  const { m, d } = parts(iso);
  return `${MONTHS[m - 1]} ${d}`;
}

/** "Nov 21, 2026" */
export function longDate(iso) {
  if (!iso) return "—";
  const { y, m, d } = parts(iso);
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

/** "Tue Nov 10, 2026" */
export function weekdayDate(iso) {
  const { y, m, d } = parts(iso);
  const weekday = WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
  return `${weekday} ${MONTHS[m - 1]} ${d}, ${y}`;
}

/** Whole days from a to b (ISO dates). */
export function daysBetween(aIso, bIso) {
  const a = parts(aIso);
  const b = parts(bIso);
  return Math.round((Date.UTC(b.y, b.m - 1, b.d) - Date.UTC(a.y, a.m - 1, a.d)) / 86_400_000);
}

export function addDays(iso, days) {
  const { y, m, d } = parts(iso);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/** Terms record {discount_bps, discount_days, net_days, anchor, prox_day} -> "2/10 net 30". */
export function termsText(t) {
  if (!t) return "none";
  const net = netText(t);
  if (!t.discount_bps) return net;
  const disc = `${trimZeros(t.discount_bps / 100)}/${t.discount_days}`;
  return `${disc} ${net.replace(/^Net/, "net")}`;
}

function netText(t) {
  if (t.anchor === "receipt") return "Due on receipt";
  if (t.anchor === "prox") return `Net ${ordinal(t.prox_day)} prox`;
  const base = t.net_days === null || t.net_days === undefined ? "no net term" : `Net ${t.net_days}`;
  return t.anchor === "eom" ? `${base} EOM` : base;
}

function ordinal(n) {
  if (!n) return "?";
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
}

function trimZeros(x) {
  return Number(x.toFixed(2)).toString();
}

/** Capitalize the first letter of a server phrase for display as a sentence. */
export function sentence(text) {
  if (!text) return "";
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function seconds(s) {
  if (s === null || s === undefined) return "—";
  return s < 10 ? `${s.toFixed(2)} s` : `${s.toFixed(1)} s`;
}
