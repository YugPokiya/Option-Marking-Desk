import type { ChainSummary } from "../api";
import { date, dateTime, strike } from "../format";

interface Props {
  chains: ChainSummary[];
  selected: number | null;
  onSelect: (id: number) => void;
}

export function ChainList({ chains, selected, onSelect }: Props) {
  if (!chains.length) return <p className="muted pad">No chains yet. Create a demo chain or upload a CSV.</p>;
  return (
    <ul className="chain-list">
      {chains.map((c) => (
        <li key={c.id}>
          <button className={c.id === selected ? "chain on" : "chain"} onClick={() => onSelect(c.id)}>
            <div className="chain-top">
              <b>{c.underlying}</b>
              <span className="muted">exp {date(c.expiry)}</span>
            </div>
            <div className="chain-meta">
              <span>spot {strike(c.spot)}</span>
              <span>{c.n_quotes} quotes</span>
              {c.latest_fit ? (
                <span className={c.latest_fit.arbitrage_free ? "pill good" : "pill bad"}>
                  {c.latest_fit.method}
                </span>
              ) : (
                <span className="pill">unmarked</span>
              )}
            </div>
            <div className="muted small">as of {dateTime(c.as_of)} · {c.source}</div>
          </button>
        </li>
      ))}
    </ul>
  );
}
