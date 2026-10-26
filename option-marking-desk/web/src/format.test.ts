import { describe, expect, it } from "vitest";
import type { Mark } from "./api";
import { atmVol, marksToCsv, vol } from "./format";

const mark: Mark = {
  strike: 25000, option_type: "C", bid: 10, ask: 11, mid: 10.5, liquid: false, reasons: ["wide_spread", "stale"],
  market_iv: 0.14, model_iv: 0.141, model_price: 10.6, mark: 10.6, mark_iv: 0.141, lower: 10, upper: 11.2, method: "model",
};

describe("format", () => {
  it("formats vols as percent", () => {
    expect(vol(0.1432)).toBe("14.32%");
    expect(vol(null)).toBe("—");
  });

  it("exports marks as CSV with joined reasons", () => {
    const [header, row] = marksToCsv([mark]).split("\n");
    expect(header.split(",")[0]).toBe("strike");
    expect(row).toContain("wide_spread|stale");
    expect(row.split(",")).toHaveLength(header.split(",").length);
  });

  it("interpolates ATM vol at k = 0", () => {
    expect(atmVol([{ k: -0.1, model_iv: 0.2 }, { k: 0.1, model_iv: 0.1 }])).toBeCloseTo(0.15);
    expect(atmVol([{ k: 0.1, model_iv: 0.2 }])).toBeNull();
  });
});
