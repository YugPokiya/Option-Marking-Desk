import type { ChainSummary, MarkRun } from "../api";
import { atmVol, daysTo, strike, vol, volPts } from "../format";

export function Kpis({ chain, run, curve }: { chain: ChainSummary; run: MarkRun; curve: { k: number; model_iv: number }[] }) {
  const f = run.fit;
  const illiquid = run.marks.filter((m) => !m.liquid).length;
  const atm = atmVol(curve);
  return (
    <div className="kpis">
      <Tile label="Forward" value={strike(f.forward)} sub={f.forward_source === "parity" ? "from put-call parity" : "from spot carry"} />
      <Tile label="ATM vol" value={vol(atm)} sub={`${daysTo(chain.as_of, chain.expiry).toFixed(1)} days to expiry`} />
      <Tile label="Fit error" value={volPts(f.rmse_vol)} sub={`${f.method.toUpperCase()} on ${f.n_points} quotes`} />
      <Tile label="Marked from model" value={`${illiquid} / ${run.marks.length}`} sub="illiquid strikes" />
      <Tile
        label="Butterfly arbitrage"
        value={f.arbitrage_free ? "None" : "Detected"}
        sub={f.min_g != null ? `min g(k) = ${f.min_g.toFixed(3)}` : "not checked for this method"}
        status={f.arbitrage_free ? "good" : "bad"}
      />
    </div>
  );
}

function Tile({ label, value, sub, status }: { label: string; value: string; sub: string; status?: "good" | "bad" }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value">
        {status && <span className={`status-dot ${status}`} aria-hidden="true">{status === "good" ? "✓" : "!"}</span>}
        {value}
      </div>
      <div className="tile-sub">{sub}</div>
    </div>
  );
}
