// Cached loaders so screens share one copy of each response. invalidate() forces a refetch.
import * as api from "./api.js";

const cache = new Map();

function once(key, loader) {
  if (!cache.has(key)) {
    const promise = loader().catch((err) => {
      cache.delete(key);
      throw err;
    });
    cache.set(key, promise);
  }
  return cache.get(key);
}

export const loadState = () => once("state", api.getState);
export const loadBills = () => once("bills", api.getBills);
export const loadForecast = () => once("forecast", api.getForecast);
export const loadPresets = () => once("presets", api.getPresets);
export const loadEvaluate = () => once("evaluate", api.getEvaluate);
export const loadCashValue = () => once("cash-value", api.getCashValue);
export const loadReview = () => once("review", api.getReview);
export const loadBill = (billId) => once(`bill:${billId}`, () => api.getBill(billId));

/** Window event fired after a change that alters /api/state (e.g. accepting a review item). */
export const STATE_CHANGED = "tempo:state-changed";

export function invalidate(...keys) {
  keys.forEach((key) => cache.delete(key));
}

/** UI-only settings that later post with Approve (autonomy has no endpoint yet). */
export const ui = {
  autonomy: null,
  runFilter: null,
};
