import type { Mark } from "./api";

const nf2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const nf0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export const px = (v: number | null | undefined) => (v == null ? "—" : nf2.format(v));
export const strike = (v: number) => nf0.format(v);
/** decimal vol -> "14.32%" */
export const vol = (v: number | null | undefined, digits = 2) => (v == null ? "—" : `${(v * 100).toFixed(digits)}%`);
/** decimal vol -> vol points "0.42 vp" */
export const volPts = (v: number) => `${(v * 100).toFixed(2)} vp`;

export const dateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
export const date = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });

export const daysTo = (fromIso: string, toIso: string) =>
  Math.max(0, (new Date(toIso).getTime() - new Date(fromIso).getTime()) / 86_400_000);

export const METHOD_LABEL: Record<string, string> = {
  market_mid: "Market mid",
  model: "Model",
  model_clipped_bid: "Model → bid",
  model_clipped_ask: "Model → ask",
  intrinsic_floor: "Intrinsic floor",
};

export const REASON_LABEL: Record<string, string> = {
  no_bid: "no bid",
  no_ask: "no ask",
  crossed: "crossed",
  wide_spread: "wide spread",
  low_volume: "low volume",
  stale: "stale",
};

/** RFC 4180 CSV of the marks table (values are numbers / fixed enums, but quote anyway). */
export function marksToCsv(marks: Mark[]): string {
  const cols: (keyof Mark)[] = [
    "strike", "option_type", "bid", "ask", "mid", "liquid", "reasons", "market_iv",
    "model_iv", "model_price", "mark", "mark_iv", "lower", "upper", "method",
  ];
  const cell = (v: unknown) => {
    const s = v == null ? "" : Array.isArray(v) ? v.join("|") : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.join(","), ...marks.map((m) => cols.map((c) => cell(m[c])).join(","))].join("\n");
}

/** Model IV at the forward, interpolated from the curve (for the ATM vol tile). */
export function atmVol(curve: { k: number; model_iv: number }[]): number | null {
  for (let i = 1; i < curve.length; i++) {
    const a = curve[i - 1], b = curve[i];
    if (a.k <= 0 && b.k >= 0) {
      const w = b.k === a.k ? 0 : (0 - a.k) / (b.k - a.k);
      return a.model_iv + w * (b.model_iv - a.model_iv);
    }
  }
  return null;
}
