import { useState } from "react";
import { api, type ChainSummary } from "../api";

/** Create a chain: synthetic demo, or a CSV upload. */
export function NewChain({ onCreated, onError }: { onCreated: (c: ChainSummary) => void; onError: (m: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);

  const run = async (fn: () => Promise<ChainSummary>) => {
    setBusy(true);
    try {
      onCreated(await fn());
      setOpen(false);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submitCsv = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    run(() => api.upload(form));
  };

  return (
    <div className="new-chain">
      <div className="row">
        <button className="btn" disabled={busy} onClick={() => run(() => api.demo(Math.floor(Math.random() * 10_000), 30))}>
          New demo chain
        </button>
        <button className="btn ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}>Upload CSV</button>
      </div>
      {open && (
        <form className="upload" onSubmit={submitCsv}>
          <label>File<input name="file" type="file" accept=".csv,text/csv" required /></label>
          <label>Underlying<input name="underlying" defaultValue="NIFTY" required /></label>
          <label>Spot<input name="spot" type="number" step="any" min="0" required /></label>
          <label>Expiry<input name="expiry" placeholder="2026-11-26T15:30:00+05:30" required /></label>
          <label>As of <span className="muted">(blank = now)</span><input name="as_of" placeholder="2026-11-02T10:05:00+05:30" /></label>
          <div className="row">
            <label>Rate<input name="rate" type="number" step="any" defaultValue="0.065" /></label>
            <label>Div yield<input name="div_yield" type="number" step="any" defaultValue="0" /></label>
          </div>
          <p className="muted small">Columns: strike, option_type (C/P/CE/PE), bid, ask, and optionally last, volume, open_interest, quote_time.</p>
          <button className="btn" disabled={busy}>Upload</button>
        </form>
      )}
    </div>
  );
}
