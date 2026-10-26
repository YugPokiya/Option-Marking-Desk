from datetime import date as date_
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OptionType = Literal["C", "P"]


class QuoteBase(BaseModel):
    strike: float = Field(gt=0)
    option_type: OptionType
    bid: float | None = Field(default=None, ge=0)
    ask: float | None = Field(default=None, ge=0)
    last: float | None = Field(default=None, ge=0)
    volume: int = Field(default=0, ge=0)
    open_interest: int = Field(default=0, ge=0)
    quote_time: datetime | None = None

    @field_validator("option_type", mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        v = str(v).strip().upper()
        return {"CALL": "C", "CE": "C", "PUT": "P", "PE": "P"}.get(v, v)


class QuoteOut(QuoteBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ChainCreate(BaseModel):
    underlying: str = Field(min_length=1, max_length=32, examples=["NIFTY"])
    expiry: datetime
    as_of: datetime
    spot: float = Field(gt=0)
    rate: float = Field(default=0.065, ge=-0.05, le=0.5, description="continuously compounded, decimal")
    div_yield: float = Field(default=0.0, ge=0, le=0.5)
    quotes: list[QuoteBase] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def _check(self) -> "ChainCreate":
        if self.expiry <= self.as_of:
            raise ValueError("expiry must be after as_of")
        if self.expiry.tzinfo is None or self.as_of.tzinfo is None:
            raise ValueError("expiry and as_of need a timezone (e.g. +05:30)")
        seen = set()
        for q in self.quotes:
            key = (q.strike, q.option_type)
            if key in seen:
                raise ValueError(f"duplicate quote for strike {q.strike} {q.option_type}")
            seen.add(key)
        return self


class FitSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    method: str
    rmse_vol: float
    arbitrage_free: bool
    n_points: int
    created_at: datetime


class ChainSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    underlying: str
    expiry: datetime
    as_of: datetime
    spot: float
    rate: float
    div_yield: float
    source: str
    created_at: datetime
    n_quotes: int = 0
    latest_fit: FitSummary | None = None


class ChainDetail(ChainSummary):
    quotes: list[QuoteOut]


class MarkingConfigIn(BaseModel):
    max_spread_pct: float = Field(default=0.10, gt=0, le=2)
    min_volume: int = Field(default=1, ge=0)
    max_quote_age_minutes: float = Field(default=15, gt=0)
    band_z: float = Field(default=2.0, gt=0, le=10)
    min_band_vol: float = Field(default=0.005, ge=0, le=0.5)


class FitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    chain_id: int
    method: str
    params: dict[str, float]
    forward: float
    forward_source: str
    discount_factor: float
    t: float
    rmse_vol: float
    n_points: int
    arbitrage_free: bool
    min_g: float | None
    k_min: float
    k_max: float
    config: dict
    duration_ms: float
    created_at: datetime


class MarkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    strike: float
    option_type: OptionType
    bid: float | None
    ask: float | None
    mid: float | None
    liquid: bool
    reasons: list[str]
    market_iv: float | None
    model_iv: float
    model_price: float
    mark: float
    mark_iv: float | None
    lower: float
    upper: float
    method: str


class MarkRunOut(BaseModel):
    fit: FitOut
    marks: list[MarkOut]


class SmilePoint(BaseModel):
    strike: float
    k: float
    model_iv: float


class MarketPoint(BaseModel):
    strike: float
    option_type: OptionType
    market_iv: float
    liquid: bool


class SmileOut(BaseModel):
    fit_id: int
    forward: float
    curve: list[SmilePoint]
    market: list[MarketPoint]


class PriceIn(BaseModel):
    spot: float = Field(gt=0)
    strike: float = Field(gt=0)
    days: float = Field(gt=0, le=3650)
    vol: float = Field(gt=0, le=5, description="decimal, 0.15 = 15%")
    rate: float = Field(default=0.065, ge=-0.05, le=0.5)
    div_yield: float = Field(default=0.0, ge=0, le=0.5)
    option_type: OptionType = "C"


class PriceOut(BaseModel):
    price: float
    forward: float
    delta: float
    vega_per_vol_point: float
    intrinsic: float


# ---------------------------------------------------------------- forecasts
class ForecastSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    symbol: str
    as_of: date_
    review_status: Literal["pass", "warn", "block"]
    created_at: datetime


class ModelInfo(BaseModel):
    id: int
    algo: str
    train_start: date_
    train_end: date_
    n_train: int
    mean_skill: float | None
    skill_by_k: dict[str, float]
    rmse_vp: dict[str, float]
    rmse_rw_vp: dict[str, float]
    hit_rate: dict[str, float | None]
    all_algos: dict[str, float]


class ForecastOut(ForecastSummary):
    grid: list[float]
    current: list[float]
    predicted: list[float]
    review: dict
    model: ModelInfo
