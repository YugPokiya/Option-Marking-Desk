import { useState } from "react";
import type { MarkingConfig } from "../api";

const FIELDS: { key: keyof MarkingConfig; label: string; step: string; hint: string; scale?: number }[] = [
  { key: "max_spread_pct", label: "Max spread", step: "1", hint: "% of mid", scale: 100 },
  { key: "min_volume", label: "Min volume", step: "1", hint: "contracts" },
  { key: "max_quote_age_minutes", label: "Max quote age", step: "1", hint: "minutes" },
  { key: "band_z", label: "Band width", step: "0.5", hint: "× fit RMSE" },
];

export function MarkControls({ cfg, onChange, onRun, busy }: {
  cfg: MarkingConfig; onChange: (c: MarkingConfig) => void; onRun: () => void; busy: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mark-controls">
      <button className="btn primary" disabled={busy} onClick={onRun}>{busy ? "Fitting…" : "Fit & mark"}</button>
      <button className="btn ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}>Liquidity rules</button>
      {open && (
        <div className="rules">
          {FIELDS.map((f) => (
            <label key={f.key}>
              {f.label}
              <span className="input-unit">
                <input
                  type="number"
                  step={f.step}
                  min="0"
                  value={+(cfg[f.key] * (f.scale ?? 1)).toFixed(4)}
                  onChange={(e) => onChange({ ...cfg, [f.key]: Number(e.target.value) / (f.scale ?? 1) })}
                />
                <span className="muted">{f.hint}</span>
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
