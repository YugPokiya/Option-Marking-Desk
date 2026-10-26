import { useMemo, useState } from "react";
import type { Mark } from "../api";
import { METHOD_LABEL, px, REASON_LABEL, strike, vol } from "../format";

type Filter = "all" | "illiquid" | "C" | "P";

export function MarksTable({ marks, onExport }: { marks: Mark[]; onExport: () => void }) {
  const [filter, setFilter] = useState<Filter>("illiquid");
  const rows = useMemo(
    () =>
      marks.filter((m) =>
        filter === "all" ? true : filter === "illiquid" ? !m.liquid : m.option_type === filter,
      ),
    [marks, filter],
  );
  const counts = {
    all: marks.length,
    illiquid: marks.filter((m) => !m.liquid).length,
    C: marks.filter((m) => m.option_type === "C").length,
    P: marks.filter((m) => m.option_type === "P").length,
  };
  const labels: Record<Filter, string> = { all: "All", illiquid: "Illiquid", C: "Calls", P: "Puts" };

  return (
    <section className="card">
      <div className="card-head">
        <h2>Marks</h2>
        <div className="seg" role="tablist" aria-label="Filter marks">
          {(Object.keys(labels) as Filter[]).map((f) => (
            <button key={f} role="tab" aria-selected={filter === f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
              {labels[f]} <span className="count">{counts[f]}</span>
            </button>
          ))}
        </div>
        <button className="btn ghost" onClick={onExport}>Export CSV</button>
      </div>
      <div className="table-wrap">
        <table className="marks">
          <thead>
            <tr>
              <th>Strike</th><th>Type</th><th className="num">Bid</th><th className="num">Ask</th>
              <th className="num">Mark</th><th className="num">Band</th><th className="num">Mark IV</th>
              <th className="num">Market IV</th><th className="num">Model IV</th><th>Method</th><th>Flags</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              <tr key={`${m.strike}${m.option_type}`} className={m.liquid ? "" : "illiquid"}>
                <td className="num">{strike(m.strike)}</td>
                <td>{m.option_type === "C" ? "Call" : "Put"}</td>
                <td className="num">{px(m.bid)}</td>
                <td className="num">{px(m.ask)}</td>
                <td className="num strong">{px(m.mark)}</td>
                <td className="num muted">{px(m.lower)} – {px(m.upper)}</td>
                <td className="num">{vol(m.mark_iv)}</td>
                <td className="num">{vol(m.market_iv)}</td>
                <td className="num">{vol(m.model_iv)}</td>
                <td><span className={`tag m-${m.method}`}>{METHOD_LABEL[m.method] ?? m.method}</span></td>
                <td className="flags">{m.reasons.map((r) => <span key={r} className="flag">{REASON_LABEL[r] ?? r}</span>)}</td>
              </tr>
            ))}
            {!rows.length && (
              <tr><td colSpan={11} className="muted center">Nothing in this view.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
