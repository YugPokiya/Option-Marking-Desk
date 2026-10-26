import type { FitSummary } from "../api";
import { dateTime, volPts } from "../format";

export function FitHistory({ fits, current, onPick }: { fits: FitSummary[]; current: number; onPick: (id: number) => void }) {
  return (
    <section className="card">
      <div className="card-head"><h2>Marking history</h2><span className="muted small">every run is kept for audit</span></div>
      <div className="table-wrap"><table className="history">
        <thead><tr><th>Run</th><th>When</th><th>Method</th><th className="num">Fit error</th><th>Arbitrage</th></tr></thead>
        <tbody>
          {fits.map((f) => (
            <tr key={f.id} className={f.id === current ? "on" : ""} onClick={() => onPick(f.id)} tabIndex={0}
                onKeyDown={(e) => e.key === "Enter" && onPick(f.id)}>
              <td>#{f.id}{f.id === current && <span className="muted"> · viewing</span>}</td>
              <td>{dateTime(f.created_at)}</td>
              <td>{f.method}</td>
              <td className="num">{volPts(f.rmse_vol)}</td>
              <td>{f.arbitrage_free ? "✓ none" : "! detected"}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </section>
  );
}
