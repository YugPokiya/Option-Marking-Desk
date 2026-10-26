"""NSE F&O bhavcopy (UDiFF format, used by NSE since July 2024).

One zipped CSV per trading day. We keep index options (IDO) and index futures (IDF) for the
requested underlyings and normalise them to a small, typed frame.
"""

from __future__ import annotations

import io
import logging
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

log = logging.getLogger(__name__)

URL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
HOME = "https://www.nseindia.com/"
HEADERS = {
    # NSE rejects requests without browser-like headers
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.nseindia.com/all-reports-derivatives",
}

REQUIRED = {
    "TradDt",
    "FinInstrmTp",
    "TckrSymb",
    "XpryDt",
    "StrkPric",
    "OptnTp",
    "ClsPric",
    "SttlmPric",
    "UndrlygPric",
    "OpnIntrst",
    "TtlTradgVol",
}
KEEP_TYPES = {"IDO": "OPT", "IDF": "FUT"}
COLUMNS = [
    "date",
    "symbol",
    "instr",
    "expiry",
    "strike",
    "opt_type",
    "close",
    "settle",
    "last",
    "underlying",
    "oi",
    "volume",
]


class BhavcopyFormatError(ValueError):
    pass


def filename(d: date) -> str:
    return f"BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"


def parse(raw: bytes | str | Path, symbols: set[str] | None = None) -> pd.DataFrame:
    """Parse one bhavcopy (zip or csv bytes/path) into the normalised frame."""
    if isinstance(raw, str | Path):
        raw = Path(raw).read_bytes()
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
            raw = zf.read(name)
    df = pd.read_csv(io.BytesIO(raw), dtype=str, skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    missing = REQUIRED - set(df.columns)
    if missing:
        raise BhavcopyFormatError(f"bhavcopy is missing columns {sorted(missing)}; has NSE changed the format?")

    df = df[df["FinInstrmTp"].str.strip().isin(KEEP_TYPES)]
    if symbols:
        df = df[df["TckrSymb"].str.strip().isin(symbols)]
    num = lambda c: pd.to_numeric(df[c], errors="coerce")  # noqa: E731
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["TradDt"].str.strip()).dt.date,
            "symbol": df["TckrSymb"].str.strip(),
            "instr": df["FinInstrmTp"].str.strip().map(KEEP_TYPES),
            "expiry": pd.to_datetime(df["XpryDt"].str.strip()).dt.date,
            "strike": num("StrkPric"),
            "opt_type": df["OptnTp"].fillna("").str.strip().map({"CE": "C", "PE": "P"}),
            "close": num("ClsPric"),
            "settle": num("SttlmPric"),
            "last": num("LastPric") if "LastPric" in df else num("ClsPric"),
            "underlying": num("UndrlygPric"),
            "oi": num("OpnIntrst").fillna(0).astype("int64"),
            "volume": num("TtlTradgVol").fillna(0).astype("int64"),
        }
    )
    out.loc[out["instr"] == "FUT", ["strike", "opt_type"]] = [None, None]
    return out[COLUMNS].reset_index(drop=True)


class Downloader:
    """Polite downloader: warms NSE cookies, retries with backoff, treats 404 as 'no trading that day'."""

    def __init__(self, cache_dir: Path | None = None, pause: float = 1.0, client: httpx.Client | None = None):
        self.cache_dir = cache_dir
        self.pause = pause
        self.client = client or httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)
        self._warmed = False

    def _warm(self) -> None:
        if not self._warmed:
            try:
                self.client.get(HOME)
            except httpx.HTTPError:
                log.warning("could not warm NSE cookies; continuing")
            self._warmed = True

    def fetch(self, d: date, attempts: int = 4) -> bytes | None:
        if self.cache_dir:
            cached = self.cache_dir / filename(d)
            if cached.exists():
                return cached.read_bytes()
        if d.weekday() >= 5:
            return None
        self._warm()
        for i in range(attempts):
            try:
                r = self.client.get(URL.format(d=d))
                if r.status_code == 404:
                    return None  # holiday, or not published yet
                r.raise_for_status()
                if r.content[:2] != b"PK":
                    raise httpx.HTTPError("response is not a zip (blocked or HTML error page)")
                if self.cache_dir:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    (self.cache_dir / filename(d)).write_bytes(r.content)
                time.sleep(self.pause)
                return r.content
            except httpx.HTTPError as e:
                wait = 2**i * self.pause
                log.warning("bhavcopy %s attempt %d failed: %s; retrying in %.0fs", d, i + 1, e, wait)
                self._warmed = False
                time.sleep(wait)
        raise RuntimeError(f"could not download bhavcopy for {d} after {attempts} attempts")


def business_days(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)
