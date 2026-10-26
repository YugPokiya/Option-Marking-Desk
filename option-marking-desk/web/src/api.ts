// Typed client for the FastAPI backend. Every call goes through /api (gateway / Vite proxy strip it).

export type OptionType = "C" | "P";

export interface FitSummary {
  id: number;
  method: string;
  rmse_vol: number;
  arbitrage_free: boolean;
  n_points: number;
  created_at: string;
}

export interface ChainSummary {
  id: number;
  underlying: string;
  expiry: string;
  as_of: string;
  spot: number;
  rate: number;
  div_yield: number;
  source: string;
  created_at: string;
  n_quotes: number;
  latest_fit: FitSummary | null;
}

export interface Fit extends FitSummary {
  chain_id: number;
  params: Record<string, number>;
  forward: number;
  forward_source: "parity" | "carry";
  discount_factor: number;
  t: number;
  min_g: number | null;
  k_min: number;
  k_max: number;
  config: MarkingConfig;
  duration_ms: number;
}

export interface Mark {
  strike: number;
  option_type: OptionType;
  bid: number | null;
  ask: number | null;
  mid: number | null;
  liquid: boolean;
  reasons: string[];
  market_iv: number | null;
  model_iv: number;
  model_price: number;
  mark: number;
  mark_iv: number | null;
  lower: number;
  upper: number;
  method: string;
}

export interface MarkRun {
  fit: Fit;
  marks: Mark[];
}

export interface Smile {
  fit_id: number;
  forward: number;
  curve: { strike: number; k: number; model_iv: number }[];
  market: { strike: number; option_type: OptionType; market_iv: number; liquid: boolean }[];
}

export interface MarkingConfig {
  max_spread_pct: number;
  min_volume: number;
  max_quote_age_minutes: number;
  band_z: number;
  min_band_vol: number;
}

export const DEFAULT_CONFIG: MarkingConfig = {
  max_spread_pct: 0.1,
  min_volume: 1,
  max_quote_age_minutes: 15,
  band_z: 2,
  min_band_vol: 0.005,
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { "content-type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  ready: () => request<{ status: string; checks: Record<string, string> }>("/readyz"),
  listChains: () => request<ChainSummary[]>("/chains?limit=100"),
  demo: (seed: number, days: number) => request<ChainSummary>(`/chains/demo?seed=${seed}&days=${days}`, { method: "POST" }),
  upload: (form: FormData) => request<ChainSummary>("/chains/upload", { method: "POST", body: form }),
  deleteChain: (id: number) => request<void>(`/chains/${id}`, { method: "DELETE" }),
  mark: (id: number, cfg: MarkingConfig) =>
    request<MarkRun>(`/chains/${id}/mark`, { method: "POST", body: JSON.stringify(cfg) }),
  marks: (id: number, fitId?: number) => request<MarkRun>(`/chains/${id}/marks${fitId ? `?fit_id=${fitId}` : ""}`),
  fits: (id: number) => request<FitSummary[]>(`/chains/${id}/fits`),
  smile: (id: number, fitId?: number) => request<Smile>(`/chains/${id}/smile?points=160${fitId ? `&fit_id=${fitId}` : ""}`),
};

// ---------------------------------------------------------------- IV forecast
export type ReviewStatus = "pass" | "warn" | "block";

export interface RuleCheck {
  check: string;
  severity: "info" | "warn" | "fail";
  detail: string;
}

export interface ClaudeIssue {
  severity: "info" | "warn" | "block";
  area: string;
  finding: string;
  evidence?: string | null;
}

export interface Forecast {
  id: number;
  symbol: string;
  as_of: string;
  review_status: ReviewStatus;
  created_at: string;
  grid: number[];
  current: number[];
  predicted: number[];
  review: {
    status: ReviewStatus;
    rule_checks: RuleCheck[];
    claude: { status: ReviewStatus; issues: ClaudeIssue[]; summary: string; confidence: string } | null;
    model_id: string | null;
    input_tokens: number;
    output_tokens: number;
    error: string | null;
  };
  model: {
    id: number;
    algo: string;
    train_start: string;
    train_end: string;
    n_train: number;
    mean_skill: number | null;
    skill_by_k: Record<string, number>;
    rmse_vp: Record<string, number>;
    rmse_rw_vp: Record<string, number>;
    hit_rate: Record<string, number | null>;
    all_algos: Record<string, number>;
  };
}

export const forecastApi = {
  latest: (symbol: string) => request<Forecast>(`/forecasts/latest?symbol=${encodeURIComponent(symbol)}`),
};
