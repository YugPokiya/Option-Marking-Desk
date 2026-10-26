import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type ChainSummary, DEFAULT_CONFIG, type FitSummary, type MarkingConfig, type MarkRun, type Smile } from "./api";
import { ChainList } from "./components/ChainList";
import { ForecastView } from "./components/ForecastView";
import { FitHistory } from "./components/FitHistory";
import { Kpis } from "./components/Kpis";
import { MarkControls } from "./components/MarkControls";
import { MarksTable } from "./components/MarksTable";
import { NewChain } from "./components/NewChain";
import { SmileChart } from "./components/SmileChart";
import { date, dateTime, marksToCsv, strike } from "./format";

export default function App() {
  const [chains, setChains] = useState<ChainSummary[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [run, setRun] = useState<MarkRun | null>(null);
  const [smile, setSmile] = useState<Smile | null>(null);
  const [fits, setFits] = useState<FitSummary[]>([]);
  const [cfg, setCfg] = useState<MarkingConfig>(DEFAULT_CONFIG);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<"ok" | "down" | "unknown">("unknown");
  const [theme, setTheme] = useState<"light" | "dark" | null>(null);
  const [view, setView] = useState<"marking" | "forecast">("marking");

  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
  }, [theme]);

  const refreshChains = useCallback(async () => {
    try {
      const list = await api.listChains();
      setChains(list);
      setSelected((s) => s ?? list[0]?.id ?? null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    refreshChains();
    const ping = () => api.ready().then(() => setHealth("ok")).catch(() => setHealth("down"));
    ping();
    const t = setInterval(ping, 30_000);
    return () => clearInterval(t);
  }, [refreshChains]);

  const load = useCallback(async (id: number, fitId?: number) => {
    setError(null);
    try {
      const [r, s, f] = await Promise.all([api.marks(id, fitId), api.smile(id, fitId), api.fits(id)]);
      setRun(r); setSmile(s); setFits(f); setCfg(r.fit.config);
    } catch (e) {
      setRun(null); setSmile(null); setFits([]);
      if (!(e instanceof ApiError && e.status === 404)) setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    if (selected != null) load(selected);
  }, [selected, load]);

  const mark = async () => {
    if (selected == null) return;
    setBusy(true); setError(null);
    try {
      await api.mark(selected, cfg);
      await Promise.all([load(selected), refreshChains()]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (selected == null || !window.confirm("Delete this chain and all its marking runs?")) return;
    await api.deleteChain(selected).catch((e) => setError(e.message));
    setSelected(null); setRun(null); setSmile(null);
    refreshChains();
  };

  const exportCsv = () => {
    if (!run || !chain) return;
    const blob = new Blob([marksToCsv(run.marks)], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `marks_${chain.underlying}_${chain.expiry.slice(0, 10)}_run${run.fit.id}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const chain = chains.find((c) => c.id === selected) ?? null;

  return (
    <div className={view === "forecast" ? "app no-side" : "app"}>
      <header className="top">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={22} height={22} />
          <span>Option Marking Desk</span>
          <nav className="tabs" aria-label="Views">
            <button className={view === "marking" ? "on" : ""} aria-current={view === "marking"} onClick={() => setView("marking")}>Marking</button>
            <button className={view === "forecast" ? "on" : ""} aria-current={view === "forecast"} onClick={() => setView("forecast")}>IV forecast</button>
          </nav>
        </div>
        <div className="top-right">
          <span className={`health ${health}`} title="API readiness (Postgres + Redis)">
            {health === "ok" ? "● Connected" : health === "down" ? "● API unavailable" : "● Checking…"}
          </span>
          <button className="btn ghost small" onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}>
            Theme
          </button>
        </div>
      </header>

      {view === "marking" && <aside className="side">
        <NewChain
          onCreated={(c) => { refreshChains(); setSelected(c.id); }}
          onError={setError}
        />
        <h3 className="side-title">Chains</h3>
        <ChainList chains={chains} selected={selected} onSelect={setSelected} />
      </aside>}

      <main className="main">
        {error && <div className="alert" role="alert">{error}<button onClick={() => setError(null)} aria-label="Dismiss">×</button></div>}

        {view === "forecast" ? <ForecastView /> : !chain ? (
          <div className="empty">
            <h1>Mark illiquid options from the smile</h1>
            <p className="muted">Create a demo NIFTY chain or upload your own quotes, then fit & mark.</p>
          </div>
        ) : (
          <>
            <div className="chain-head">
              <div>
                <h1>{chain.underlying} <span className="muted">· {date(chain.expiry)} expiry</span></h1>
                <p className="muted">
                  Spot {strike(chain.spot)} · rate {(chain.rate * 100).toFixed(2)}% · div {(chain.div_yield * 100).toFixed(2)}% ·
                  as of {dateTime(chain.as_of)} · {chain.n_quotes} quotes
                </p>
              </div>
              <div className="row">
                <MarkControls cfg={cfg} onChange={setCfg} onRun={mark} busy={busy} />
                <button className="btn ghost danger" onClick={remove}>Delete</button>
              </div>
            </div>

            {run && smile ? (
              <div className={busy ? "content refetch" : "content"}>
                <Kpis chain={chain} run={run} curve={smile.curve} />
                <section className="card">
                  <div className="card-head">
                    <h2>Implied volatility smile</h2>
                    <span className="muted small">run #{run.fit.id} · {run.fit.duration_ms.toFixed(0)} ms</span>
                  </div>
                  <SmileChart smile={smile} spot={chain.spot} />
                </section>
                <MarksTable marks={run.marks} onExport={exportCsv} />
                {fits.length > 0 && <FitHistory fits={fits} current={run.fit.id} onPick={(id) => load(chain.id, id)} />}
              </div>
            ) : (
              <div className="empty small-empty">
                <p>This chain hasn’t been marked yet.</p>
                <p className="muted">“Fit & mark” classifies each quote, fits an SVI smile to the liquid ones and prices every strike.</p>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
