import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, type Forecast, forecastApi } from "../api";
import { date, vol } from "../format";

const SYMBOLS = ["NIFTY", "BANKNIFTY"];
const STATUS_TEXT = { pass: "Published", warn: "Published with warnings", block: "Blocked: not published" } as const;
const ALGO_TEXT: Record<string, string> = { rw: "No change (random walk)", ridge: "Ridge regression", gbr: "Gradient boosting" };
const col = (k: number) => `iv_${k >= 0 ? "+" : "-"}${Math.abs(k).toFixed(3)}`;
const pct = (k: number) => `${k > 0 ? "+" : ""}${(k * 100).toFixed(1)}%`;

export function ForecastView() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [fc, setFc] = useState<Forecast | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "none" | "error">("loading");
  const [err, setErr] = useState("");

  useEffect(() => {
    setState("loading");
    forecastApi.latest(symbol)
      .then((f) => { setFc(f); setState("ok"); })
      .catch((e) => {
        setFc(null);
        if (e instanceof ApiError && e.status === 404) setState("none");
        else { setErr(e.message); setState("error"); }
      });
  }, [symbol]);

  return (
    <div className="content">
      <div className="chain-head">
        <div>
          <h1>Next-session IV forecast</h1>
          <p className="muted">30-day constant-maturity smile from NSE end-of-day data. Reviewed by rule checks and Claude before publishing.</p>
        </div>
        <div className="seg" role="tablist" aria-label="Underlying">
          {SYMBOLS.map((s) => (
            <button key={s} role="tab" aria-selected={s === symbol} className={s === symbol ? "on" : ""} onClick={() => setSymbol(s)}>{s}</button>
          ))}
        </div>
      </div>

      {state === "none" && (
        <div className="empty small-empty">
          <p>No forecast for {symbol} yet.</p>
          <p className="muted">Run <code>python -m app.forecast backfill --from 2024-01-01</code>, then <code>run-daily</code>.</p>
        </div>
      )}
      {state === "error" && <div className="alert" role="alert">{err}</div>}
      {state === "ok" && fc && <ForecastBody fc={fc} />}
    </div>
  );
}

function ForecastBody({ fc }: { fc: Forecast }) {
  const r = fc.review;
  const m = fc.model;
  return (
    <>
      <section className={`status-banner ${fc.review_status}`} aria-live="polite">
        <span className="status-icon" aria-hidden="true">{fc.review_status === "pass" ? "✓" : fc.review_status === "warn" ? "!" : "✕"}</span>
        <div>
          <b>{STATUS_TEXT[fc.review_status]}</b>
          <span className="muted"> · as of {date(fc.as_of)} close</span>
          {r.claude ? (
            <p className="claude-summary"><span className="muted">Claude: </span>{r.claude.summary}</p>
          ) : (
            <p className="muted">{r.error === "claude review disabled" ? "Claude review was off for this run, so only the rule checks were applied."
              : `Claude review unavailable (${r.error ?? "unknown"}).`}</p>
          )}
        </div>
      </section>

      <div className="kpis">
        <Tile label="ATM vol today" value={vol(fc.current[fc.grid.indexOf(0)])} sub="30-day, at the forward" />
        <Tile label="ATM vol forecast" value={vol(fc.predicted[fc.grid.indexOf(0)])}
              sub={`${((fc.predicted[fc.grid.indexOf(0)] - fc.current[fc.grid.indexOf(0)]) * 100).toFixed(2)} vp change`} />
        <Tile label="Model" value={m.algo === "rw" ? "No change" : m.algo.toUpperCase()} sub={ALGO_TEXT[m.algo] ?? m.algo} />
        <Tile label="Out-of-sample skill" value={m.mean_skill == null ? "—" : `${(m.mean_skill * 100).toFixed(1)}%`}
              sub="RMSE improvement vs no-change" />
      </div>

      <section className="card">
        <div className="card-head"><h2>Smile: today vs forecast</h2><span className="muted small">model #{m.id}, trained to {date(m.train_end)}</span></div>
        <ForecastChart fc={fc} />
      </section>

      <section className="card">
        <div className="card-head"><h2>By moneyness</h2><span className="muted small">walk-forward backtest on {m.n_train} sessions</span></div>
        <div className="table-wrap">
          <table>
            <thead><tr>
              <th>Strike vs forward</th><th className="num">Today</th><th className="num">Forecast</th><th className="num">Change</th>
              <th className="num">Model error</th><th className="num">No-change error</th><th className="num">Skill</th><th className="num">Direction hit</th>
            </tr></thead>
            <tbody>
              {fc.grid.map((k, i) => {
                const c = col(k);
                return (
                  <tr key={k}>
                    <td className="num">{pct(k)}</td>
                    <td className="num">{vol(fc.current[i])}</td>
                    <td className="num strong">{vol(fc.predicted[i])}</td>
                    <td className="num">{((fc.predicted[i] - fc.current[i]) * 100).toFixed(2)} vp</td>
                    <td className="num">{m.rmse_vp[c]?.toFixed(2) ?? "—"} vp</td>
                    <td className="num">{m.rmse_rw_vp[c]?.toFixed(2) ?? "—"} vp</td>
                    <td className="num">{m.skill_by_k[c] != null ? `${(m.skill_by_k[c] * 100).toFixed(1)}%` : "—"}</td>
                    <td className="num">{m.algo === "rw" || m.hit_rate[c] == null ? "—" : `${((m.hit_rate[c] as number) * 100).toFixed(0)}%`}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="muted small" style={{ marginTop: 8 }}>
          Candidates tried: {Object.entries(m.all_algos).map(([a, s]) => `${ALGO_TEXT[a] ?? a} ${(s * 100).toFixed(1)}%`).join(" · ")}.
          A model is only used if it beats “no change” out of sample.
        </p>
      </section>

      <section className="card">
        <div className="card-head"><h2>Review</h2>
          <span className="muted small">{r.model_id ?? "rules only"}{r.input_tokens ? ` · ${r.input_tokens + r.output_tokens} tokens` : ""}</span>
        </div>
        <ul className="review-list">
          {r.claude?.issues.map((i, n) => (
            <li key={`c${n}`} className={`sev-${i.severity}`}>
              <span className="sev">{i.severity}</span><span className="area">Claude · {i.area}</span>
              <span>{i.finding}{i.evidence ? <span className="muted"> ({i.evidence})</span> : null}</span>
            </li>
          ))}
          {r.rule_checks.map((c, n) => (
            <li key={`r${n}`} className={`sev-${c.severity}`}>
              <span className="sev">{c.severity}</span><span className="area">rule · {c.check}</span><span>{c.detail}</span>
            </li>
          ))}
          {!r.rule_checks.length && !r.claude?.issues.length && <li className="muted">No issues raised.</li>}
        </ul>
      </section>
    </>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="tile"><div className="tile-label">{label}</div><div className="tile-value">{value}</div><div className="tile-sub">{sub}</div></div>
  );
}

const M = { top: 16, right: 20, bottom: 40, left: 52 };
const H = 280;

function ForecastChart({ fc }: { fc: Forecast }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(700);
  const [hover, setHover] = useState<number | null>(null);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(300, e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const g = useMemo(() => {
    const ys = [...fc.current, ...fc.predicted];
    const pad = (Math.max(...ys) - Math.min(...ys)) * 0.15 || 0.005;
    const y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
    const x0 = fc.grid[0], x1 = fc.grid[fc.grid.length - 1];
    const iw = w - M.left - M.right, ih = H - M.top - M.bottom;
    const sx = (v: number) => M.left + ((v - x0) / (x1 - x0)) * iw;
    const sy = (v: number) => M.top + (1 - (v - y0) / (y1 - y0)) * ih;
    const line = (vals: number[]) => vals.map((v, i) => `${i ? "L" : "M"}${sx(fc.grid[i]).toFixed(1)},${sy(v).toFixed(1)}`).join("");
    const step = (y1 - y0) / 4;
    return { sx, sy, iw, ih, y0, today: line(fc.current), fcst: line(fc.predicted), yt: [0, 1, 2, 3, 4].map((i) => y0 + i * step) };
  }, [fc, w]);

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const x = e.clientX - e.currentTarget.getBoundingClientRect().left;
    let best = 0;
    fc.grid.forEach((k, i) => { if (Math.abs(g.sx(k) - x) < Math.abs(g.sx(fc.grid[best]) - x)) best = i; });
    setHover(x >= M.left - 10 && x <= M.left + g.iw + 10 ? best : null);
  };

  return (
    <figure className="chart" ref={wrap}>
      <div className="legend" aria-hidden="true">
        <span><i className="key key-line" /> Today’s close</span>
        <span><i className="key key-dash" /> Forecast, next session</span>
      </div>
      <svg width="100%" viewBox={`0 0 ${w} ${H}`} role="img" aria-label="Today's 30-day smile and the forecast for the next session; the table below lists every value"
           onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
        {g.yt.map((t) => (
          <g key={t}>
            <line className="grid" x1={M.left} x2={M.left + g.iw} y1={g.sy(t)} y2={g.sy(t)} />
            <text className="tick" x={M.left - 8} y={g.sy(t)} dy="0.32em" textAnchor="end">{vol(t, 1)}</text>
          </g>
        ))}
        {fc.grid.filter((k) => g.iw >= 520 || Math.abs(Math.abs(k) - 0.025) > 1e-9).map((k) => (
          <text key={k} className="tick" x={g.sx(k)} y={H - M.bottom + 18} textAnchor="middle">{pct(k)}</text>
        ))}
        <text className="axis-title" x={M.left + g.iw / 2} y={H - 4} textAnchor="middle">Strike vs forward (log-moneyness)</text>
        <line className="baseline" x1={M.left} x2={M.left + g.iw} y1={M.top + g.ih} y2={M.top + g.ih} />
        <path className="curve" d={g.today} />
        <path className="curve-fcst" d={g.fcst} />
        {fc.grid.map((k, i) => (
          <g key={k}>
            <circle className="pt-focus" cx={g.sx(k)} cy={g.sy(fc.current[i])} r={3.5} />
            <circle className="pt pt-liquid" cx={g.sx(k)} cy={g.sy(fc.predicted[i])} r={3.5} />
          </g>
        ))}
        {hover != null && <line className="crosshair" x1={g.sx(fc.grid[hover])} x2={g.sx(fc.grid[hover])} y1={M.top} y2={M.top + g.ih} />}
      </svg>
      {hover != null && (
        <div className="tooltip" style={{ left: Math.min(g.sx(fc.grid[hover]) + 14, w - 190), top: 30 }} role="status">
          <div className="tt-title">Strike {pct(fc.grid[hover])} vs forward</div>
          <div className="tt-row"><i className="key key-line" /><b>{vol(fc.current[hover])}</b><span>today</span></div>
          <div className="tt-row"><i className="key key-dash" /><b>{vol(fc.predicted[hover])}</b><span>forecast</span></div>
        </div>
      )}
    </figure>
  );
}
