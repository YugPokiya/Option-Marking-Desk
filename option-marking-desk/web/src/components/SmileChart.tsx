import { useEffect, useMemo, useRef, useState } from "react";
import type { Smile } from "../api";
import { strike as fmtStrike, vol } from "../format";

interface Props {
  smile: Smile;
  spot: number;
}

const M = { top: 16, right: 20, bottom: 40, left: 52 };
const HEIGHT = 340;

function ticks(min: number, max: number, count: number): number[] {
  const span = max - min;
  const raw = span / count;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => span / s <= count) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

/** Implied-vol smile: fitted curve (line) + market quotes (filled = liquid, ring = illiquid). */
export function SmileChart({ smile, spot }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [hoverX, setHoverX] = useState<number | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(320, e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const geo = useMemo(() => {
    const xs = [...smile.curve.map((p) => p.strike), ...smile.market.map((p) => p.strike)];
    const ys = [...smile.curve.map((p) => p.model_iv), ...smile.market.map((p) => p.market_iv)];
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const yPad = (Math.max(...ys) - Math.min(...ys)) * 0.08 || 0.01;
    const y0 = Math.max(0, Math.min(...ys) - yPad), y1 = Math.max(...ys) + yPad;
    const iw = width - M.left - M.right, ih = HEIGHT - M.top - M.bottom;
    const sx = (v: number) => M.left + ((v - x0) / (x1 - x0)) * iw;
    const sy = (v: number) => M.top + (1 - (v - y0) / (y1 - y0)) * ih;
    const path = smile.curve.map((p, i) => `${i ? "L" : "M"}${sx(p.strike).toFixed(1)},${sy(p.model_iv).toFixed(1)}`).join("");
    return { x0, x1, y0, y1, iw, ih, sx, sy, path, xt: ticks(x0, x1, Math.max(3, Math.floor(iw / 90))), yt: ticks(y0, y1, 5) };
  }, [smile, width]);

  // crosshair snaps to the nearest market strike (where the quotes are), else the curve
  const strikes = useMemo(() => [...new Set(smile.market.map((m) => m.strike))].sort((a, b) => a - b), [smile]);
  const hover = useMemo(() => {
    if (hoverX == null) return null;
    const target = geo.x0 + ((hoverX - M.left) / geo.iw) * (geo.x1 - geo.x0);
    const k = strikes.length
      ? strikes.reduce((best, s) => (Math.abs(s - target) < Math.abs(best - target) ? s : best), strikes[0])
      : target;
    const c = smile.curve.reduce((best, p) => (Math.abs(p.strike - k) < Math.abs(best.strike - k) ? p : best), smile.curve[0]);
    const quotes = smile.market.filter((m) => m.strike === k);
    return { strike: k, model: c.model_iv, quotes };
  }, [hoverX, geo, smile, strikes]);

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - r.left;
    setHoverX(x >= M.left && x <= M.left + geo.iw ? x : null);
  };

  const tipLeft = hover ? Math.min(geo.sx(hover.strike) + 14, width - 200) : 0;

  return (
    <figure className="chart" ref={wrap}>
      <div className="legend" aria-hidden="true">
        <span><i className="key key-line" /> Fitted smile</span>
        <span><i className="key key-dot" /> Liquid quote</span>
        <span><i className="key key-ring" /> Illiquid quote</span>
        <span><i className="key key-fwd" /> Forward {fmtStrike(smile.forward)}</span>
      </div>
      <svg
        width="100%"
        viewBox={`0 0 ${width} ${HEIGHT}`}
        role="img"
        aria-label={`Implied volatility smile with ${smile.market.length} market quotes; the marks table below lists every value`}
        onPointerMove={onMove}
        onPointerLeave={() => setHoverX(null)}
      >
        {geo.yt.map((t) => (
          <g key={`y${t}`}>
            <line className="grid" x1={M.left} x2={M.left + geo.iw} y1={geo.sy(t)} y2={geo.sy(t)} />
            <text className="tick" x={M.left - 8} y={geo.sy(t)} dy="0.32em" textAnchor="end">{vol(t, 0)}</text>
          </g>
        ))}
        {geo.xt.map((t) => (
          <text key={`x${t}`} className="tick" x={geo.sx(t)} y={HEIGHT - M.bottom + 18} textAnchor="middle">{fmtStrike(t)}</text>
        ))}
        <text className="axis-title" x={M.left + geo.iw / 2} y={HEIGHT - 4} textAnchor="middle">Strike</text>
        <line className="baseline" x1={M.left} x2={M.left + geo.iw} y1={M.top + geo.ih} y2={M.top + geo.ih} />

        {smile.forward >= geo.x0 && smile.forward <= geo.x1 && (
          <line className="fwd" x1={geo.sx(smile.forward)} x2={geo.sx(smile.forward)} y1={M.top} y2={M.top + geo.ih} />
        )}
        {spot >= geo.x0 && spot <= geo.x1 && (
          <text className="tick" x={geo.sx(spot)} y={M.top + 10} textAnchor="middle">spot</text>
        )}

        <path className="curve" d={geo.path} />
        {smile.market.map((m) => (
          <circle
            key={`${m.strike}${m.option_type}`}
            className={m.liquid ? "pt pt-liquid" : "pt pt-illiquid"}
            cx={geo.sx(m.strike)}
            cy={geo.sy(m.market_iv)}
            r={4}
          />
        ))}

        {hover && (
          <g pointerEvents="none">
            <line className="crosshair" x1={geo.sx(hover.strike)} x2={geo.sx(hover.strike)} y1={M.top} y2={M.top + geo.ih} />
            <circle className="pt-focus" cx={geo.sx(hover.strike)} cy={geo.sy(hover.model)} r={5} />
          </g>
        )}
      </svg>
      {hover && (
        <div className="tooltip" style={{ left: tipLeft, top: 36 }} role="status">
          <div className="tt-title">Strike {fmtStrike(hover.strike)}</div>
          <div className="tt-row"><i className="key key-line" /><b>{vol(hover.model)}</b><span>model</span></div>
          {hover.quotes.map((q) => (
            <div className="tt-row" key={q.option_type}>
              <i className={q.liquid ? "key key-dot" : "key key-ring"} />
              <b>{vol(q.market_iv)}</b>
              <span>{q.option_type === "C" ? "call" : "put"} · {q.liquid ? "liquid" : "illiquid"}</span>
            </div>
          ))}
        </div>
      )}
      <figcaption className="muted">
        Out-of-the-money liquid quotes are fitted; every strike is then priced off the curve. Hover for values.
      </figcaption>
    </figure>
  );
}
