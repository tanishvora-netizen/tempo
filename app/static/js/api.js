// One function per endpoint. Every response is {"data": {...}}; errors carry a readable message
// (FastAPI validation errors, HTTPException details, and Tempo's {"error","detail"} bodies).

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function detailMessage(body, status) {
  if (!body) return `Request failed (${status})`;
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail) && body.detail.length) {
    return body.detail.map((d) => `${(d.loc || []).slice(-1)[0] ?? "input"}: ${d.msg}`).join("; ");
  }
  if (typeof body.error === "string") return body.error;
  return `Request failed (${status})`;
}

async function request(method, path, payload) {
  const init = { method, headers: { Accept: "application/json" } };
  if (payload !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(payload);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError(0, "Cannot reach the Tempo server. Check that it is running, then retry.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, detailMessage(body, response.status));
  if (!body || typeof body.data !== "object") throw new ApiError(response.status, "The server sent an unexpected response.");
  return body.data;
}

export const getState = () => request("GET", "/api/state");
export const getBills = () => request("GET", "/api/bills");
export const getBill = (billId) => request("GET", `/api/bills/${encodeURIComponent(billId)}`);
export const getReview = () => request("GET", "/api/review");
export const acceptReview = (billId) => request("POST", `/api/review/${encodeURIComponent(billId)}`, { action: "accept" });
export const editReview = (billId, terms) =>
  request("POST", `/api/review/${encodeURIComponent(billId)}`, { action: "edit", terms });
export const getForecast = () => request("GET", "/api/forecast");
export const getPresets = () => request("GET", "/api/whatif/presets");
export const runWhatIf = (whatIf) => request("POST", "/api/optimize", { what_if: whatIf });
export const getEvaluate = () => request("GET", "/api/evaluate");
export const getCashValue = () => request("GET", "/api/cash-value");

// Negotiation agent (directive 5.7, 7.6). Nothing is ever sent to a vendor.
const vendorPath = (vendorId) => `/api/negotiate/${encodeURIComponent(vendorId)}`;
export const getOffers = () => request("GET", "/api/negotiate");
export const draftOffer = (vendorId) => request("POST", vendorPath(vendorId));
export const simulateReply = (vendorId, kind) => request("POST", `${vendorPath(vendorId)}/reply`, { kind });
export const acceptNegotiated = (vendorId, terms) => request("POST", `${vendorPath(vendorId)}/accept`, { terms });

// Approval, audit chain, and Ramp payload preview (directive 8.3, 8.4). Ramp is never called.
export const approvePlan = (approver, autonomy) => request("POST", "/api/plan/approve", { approver, autonomy });
export const getAudit = () => request("GET", "/api/audit");
export const getPayloadPreview = () => request("GET", "/api/ramp/payload-preview");
