from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JsonType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class Chain(Base):
    """One snapshot of an option chain for a single underlying + expiry."""

    __tablename__ = "chains"

    id: Mapped[int] = mapped_column(primary_key=True)
    underlying: Mapped[str] = mapped_column(String(32))
    expiry: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    spot: Mapped[float] = mapped_column(Float)
    rate: Mapped[float] = mapped_column(Float)
    div_yield: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(16), default="api")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    quotes: Mapped[list["Quote"]] = relationship(
        back_populates="chain", cascade="all, delete-orphan", order_by="Quote.strike"
    )
    fits: Mapped[list["SmileFit"]] = relationship(
        back_populates="chain", cascade="all, delete-orphan", order_by="SmileFit.id.desc()"
    )

    __table_args__ = (Index("ix_chains_underlying_expiry_asof", "underlying", "expiry", "as_of"),)


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    chain_id: Mapped[int] = mapped_column(ForeignKey("chains.id", ondelete="CASCADE"), index=True)
    strike: Mapped[float] = mapped_column(Float)
    option_type: Mapped[str] = mapped_column(String(1))
    bid: Mapped[float | None] = mapped_column(Float)
    ask: Mapped[float | None] = mapped_column(Float)
    last: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer, default=0)
    open_interest: Mapped[int] = mapped_column(Integer, default=0)
    quote_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    chain: Mapped[Chain] = relationship(back_populates="quotes")

    __table_args__ = (UniqueConstraint("chain_id", "strike", "option_type", name="uq_quotes_chain_strike_type"),)


class SmileFit(Base):
    """One marking run: the fitted smile plus the config it ran with. Marks hang off it (audit trail)."""

    __tablename__ = "smile_fits"

    id: Mapped[int] = mapped_column(primary_key=True)
    chain_id: Mapped[int] = mapped_column(ForeignKey("chains.id", ondelete="CASCADE"), index=True)
    method: Mapped[str] = mapped_column(String(16))
    params: Mapped[dict] = mapped_column(JsonType)
    forward: Mapped[float] = mapped_column(Float)
    forward_source: Mapped[str] = mapped_column(String(16))
    discount_factor: Mapped[float] = mapped_column(Float)
    t: Mapped[float] = mapped_column(Float)
    rmse_vol: Mapped[float] = mapped_column(Float)
    n_points: Mapped[int] = mapped_column(Integer)
    arbitrage_free: Mapped[bool] = mapped_column(Boolean)
    min_g: Mapped[float | None] = mapped_column(Float)
    k_min: Mapped[float] = mapped_column(Float)
    k_max: Mapped[float] = mapped_column(Float)
    config: Mapped[dict] = mapped_column(JsonType)
    duration_ms: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chain: Mapped[Chain] = relationship(back_populates="fits")
    marks: Mapped[list["Mark"]] = relationship(
        back_populates="fit", cascade="all, delete-orphan", order_by="(Mark.strike, Mark.option_type)"
    )


class Mark(Base):
    __tablename__ = "marks"

    id: Mapped[int] = mapped_column(primary_key=True)
    fit_id: Mapped[int] = mapped_column(ForeignKey("smile_fits.id", ondelete="CASCADE"), index=True)
    strike: Mapped[float] = mapped_column(Float)
    option_type: Mapped[str] = mapped_column(String(1))
    bid: Mapped[float | None] = mapped_column(Float)
    ask: Mapped[float | None] = mapped_column(Float)
    mid: Mapped[float | None] = mapped_column(Float)
    liquid: Mapped[bool] = mapped_column(Boolean)
    reasons: Mapped[list] = mapped_column(JsonType)
    market_iv: Mapped[float | None] = mapped_column(Float)
    model_iv: Mapped[float] = mapped_column(Float)
    model_price: Mapped[float] = mapped_column(Float)
    mark: Mapped[float] = mapped_column(Float)
    mark_iv: Mapped[float | None] = mapped_column(Float)
    lower: Mapped[float] = mapped_column(Float)
    upper: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(24))

    fit: Mapped[SmileFit] = relationship(back_populates="marks")


# ---------------------------------------------------------------- IV forecasting (app/forecast)
from datetime import date as _date  # noqa: E402

from sqlalchemy import BigInteger, Date, LargeBinary  # noqa: E402


class BhavContract(Base):
    """Raw end-of-day contract from the NSE F&O bhavcopy (futures: strike 0, opt_type 'F')."""

    __tablename__ = "bhav_contracts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    date: Mapped[_date] = mapped_column(Date)
    symbol: Mapped[str] = mapped_column(String(32))
    instr: Mapped[str] = mapped_column(String(3))
    expiry: Mapped[_date] = mapped_column(Date)
    strike: Mapped[float] = mapped_column(Float)
    opt_type: Mapped[str] = mapped_column(String(1))
    close: Mapped[float | None] = mapped_column(Float)
    settle: Mapped[float | None] = mapped_column(Float)
    last: Mapped[float | None] = mapped_column(Float)
    underlying: Mapped[float | None] = mapped_column(Float)
    oi: Mapped[int] = mapped_column(BigInteger)
    volume: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint("date", "symbol", "instr", "expiry", "strike", "opt_type", name="uq_bhav_contract"),
        Index("ix_bhav_symbol_date", "symbol", "date"),
    )


class IVSurface(Base):
    """Daily 30-day constant-maturity smile on the moneyness grid + fit diagnostics."""

    __tablename__ = "iv_surfaces"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    spot: Mapped[float] = mapped_column(Float)
    ivs: Mapped[dict] = mapped_column(JsonType)
    stats: Mapped[dict] = mapped_column(JsonType)


class ForecastModel(Base):
    __tablename__ = "forecast_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    algo: Mapped[str] = mapped_column(String(16))
    train_start: Mapped[_date] = mapped_column(Date)
    train_end: Mapped[_date] = mapped_column(Date)
    n_train: Mapped[int] = mapped_column(Integer)
    features: Mapped[list] = mapped_column(JsonType)
    backtest: Mapped[dict] = mapped_column(JsonType)  # skill of every algo, walk-forward
    blob: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IVForecast(Base):
    __tablename__ = "iv_forecasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32))
    as_of: Mapped[_date] = mapped_column(Date)
    model_id: Mapped[int] = mapped_column(ForeignKey("forecast_models.id", ondelete="RESTRICT"))
    grid: Mapped[list] = mapped_column(JsonType)
    current: Mapped[list] = mapped_column(JsonType)
    predicted: Mapped[list] = mapped_column(JsonType)
    review_status: Mapped[str] = mapped_column(String(8))  # pass | warn | block
    review: Mapped[dict] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    model: Mapped[ForecastModel] = relationship()

    __table_args__ = (UniqueConstraint("symbol", "as_of", name="uq_forecast_symbol_asof"),)
