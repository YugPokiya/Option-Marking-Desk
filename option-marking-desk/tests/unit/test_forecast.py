import io
import json
import zipfile
from datetime import date, timedelta

import httpx
import numpy as np
import pytest

from app.forecast import bhavcopy
from app.forecast.features import FEATURE_COLS, TARGET_COLS, make_features, training_frame
from app.forecast.model import backtest_all, choose, dumps, fit_final, loads
from app.forecast.review import build_payload, review
from app.forecast.sanity import Check, run_checks
from app.forecast.surface import GRID_COLS, daily_surface
from app.forecast.synthetic import generate, surface_frame
from tests.forecast_fakes import PASS, FakeBedrock


@pytest.fixture(scope="module")
def bhav_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("bhav")
    days = generate(d, days=3, strike_step=100, seed=1)
    return d, days


# ---------------------------------------------------------------- bhavcopy
def test_parse_udiff_zip(bhav_dir):
    d, days = bhav_dir
    f = bhavcopy.parse(d / bhavcopy.filename(days[-1]), {"NIFTY"})
    assert list(f.columns) == bhavcopy.COLUMNS
    assert set(f["instr"]) == {"OPT", "FUT"} and set(f.loc[f.instr == "OPT", "opt_type"]) == {"C", "P"}
    assert f.loc[f.instr == "FUT", "strike"].isna().all()
    assert (f["date"] == days[-1]).all()


def test_parse_rejects_unknown_format():
    raw = b"SYMBOL,EXPIRY,STRIKE\nNIFTY,2026-01-01,100\n"
    with pytest.raises(bhavcopy.BhavcopyFormatError, match="missing columns"):
        bhavcopy.parse(raw)


def _zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.csv", text)
    return buf.getvalue()


def test_downloader_handles_holidays_and_bad_responses(tmp_path):
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.url.path)
        if "20261023" in req.url.path:
            return httpx.Response(200, content=_zip("a,b\n1,2\n"))
        if "20261022" in req.url.path:
            return httpx.Response(200, text="<html>Access denied</html>")
        if "20261021" in req.url.path:
            return httpx.Response(404)
        return httpx.Response(200, text="home")

    dl = bhavcopy.Downloader(cache_dir=tmp_path, pause=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert dl.fetch(date(2026, 10, 23))[:2] == b"PK"
    assert (tmp_path / bhavcopy.filename(date(2026, 10, 23))).exists()  # cached
    assert dl.fetch(date(2026, 10, 21)) is None  # 404 = no session
    assert dl.fetch(date(2026, 10, 24)) is None  # Saturday, no request
    with pytest.raises(RuntimeError):
        dl.fetch(date(2026, 10, 22), attempts=2)  # HTML instead of zip


# ---------------------------------------------------------------- surface
def test_daily_surface_from_bhavcopy(bhav_dir):
    d, days = bhav_dir
    row = daily_surface(bhavcopy.parse(d / bhavcopy.filename(days[-1]), {"NIFTY"}))
    assert row and row["n_expiries_fit"] == 2 and row["all_arb_free"]
    ivs = [row[c] for c in GRID_COLS]
    assert all(0.05 < v < 0.5 for v in ivs)
    assert ivs[0] > ivs[3] > ivs[-1] * 0.95  # equity-style skew: puts richer than calls
    assert row["max_rmse_vol"] < 0.01
    assert "future" in row["forward_sources"]


# ---------------------------------------------------------------- features + model
def test_targets_are_next_day_changes():
    feat = make_features(surface_frame(40, seed=1))
    assert feat[TARGET_COLS].iloc[-1].isna().all()  # tomorrow unknown for the last row
    assert feat["d_iv_+0.000"].iloc[5] == pytest.approx(feat["iv_+0.000"].iloc[6] - feat["iv_+0.000"].iloc[5])
    assert len(training_frame(feat)) < len(feat)


def test_model_finds_real_signal_and_rejects_noise():
    signal = training_frame(make_features(surface_frame(420, kappa=0.35, leverage=0.3, seed=3)))
    sk = backtest_all(signal, algos=("rw", "ridge"))
    assert sk["ridge"].mean_skill > 0.03 and choose(sk) == "ridge"

    noise = training_frame(make_features(surface_frame(420, kappa=0.0, leverage=0.0, seed=3)))
    sk = backtest_all(noise, algos=("rw", "ridge"))
    assert choose(sk) == "rw"  # never publish a model that does not beat "no change"


def test_model_round_trip():
    tr = training_frame(make_features(surface_frame(150, seed=2)))
    m = fit_final(tr, "ridge")
    x = tr[FEATURE_COLS].iloc[-3:].to_numpy(float)
    np.testing.assert_allclose(loads(dumps(m)).predict(x), m.predict(x))


# ---------------------------------------------------------------- checks + review
@pytest.fixture
def ctx():
    surf = surface_frame(120, seed=4)
    feat = make_features(surf)
    row = surf.iloc[-1].to_dict()
    meta = {"algo": "ridge", "rmse_rw_vp": {c: 0.6 for c in GRID_COLS}, "mean_skill": 0.04, "version": 1}
    return surf, feat, row, meta


def _checks(ctx, delta, today=None):
    surf, feat, row, meta = ctx
    return run_checks(
        today=today or row["date"],
        surf_row=row,
        history=surf,
        feat_row=feat.iloc[-1],
        feat_hist=feat.iloc[:-1],
        predicted_delta=delta,
        model_meta=meta,
    )


def test_checks_pass_quiet_day(ctx):
    assert not [c for c in _checks(ctx, dict.fromkeys(GRID_COLS, 0.001)) if c.severity == "fail"]


def test_checks_fail_extreme_forecast_and_stale_data(ctx):
    names = {(c.check, c.severity) for c in _checks(ctx, dict.fromkeys(GRID_COLS, 0.08))}
    assert ("prediction_size", "fail") in names
    stale = _checks(ctx, dict.fromkeys(GRID_COLS, 0.0), today=ctx[2]["date"] + timedelta(days=20))
    assert ("freshness", "fail") in {(c.check, c.severity) for c in stale}


def _payload(ctx, checks):
    surf, feat, row, meta = ctx
    return build_payload(
        surf_row=row,
        prev_row=surf.iloc[-2].to_dict(),
        recent=surf.tail(10).to_dict("records"),
        predicted=dict.fromkeys(GRID_COLS, 0.002),
        model_meta=meta,
        checks=checks,
        feature_row=feat.iloc[-1].to_dict(),
    )


def test_payload_is_compact_json(ctx):
    p = _payload(ctx, [])
    s = json.dumps(p, default=str)
    assert len(s) < 6000 and len(p["smile_today"]) == len(GRID_COLS)


def test_review_uses_tool_and_records_tokens(ctx):
    fake = FakeBedrock(verdict=PASS)
    r = review(_payload(ctx, []), [], client=fake, model_id="in.anthropic.claude-sonnet-5")
    assert r.status == "pass" and r.input_tokens == 1234 and r.output_tokens == 210
    call = fake.calls[0]
    assert call["modelId"] == "in.anthropic.claude-sonnet-5"
    assert call["toolConfig"]["tools"][0]["toolSpec"]["name"] == "submit_review"
    assert "do NOT forecast" in call["system"][0]["text"]


def test_review_cannot_clear_a_rule_failure(ctx):
    rule_fail = [Check("prediction_level", "fail", "x")]
    r = review(_payload(ctx, []), rule_fail, client=FakeBedrock(verdict=PASS), model_id="m")
    assert r.status == "block"


def test_review_can_raise_severity(ctx):
    warn = PASS | {"status": "warn", "issues": [{"severity": "warn", "area": "calendar", "finding": "3-day gap"}]}
    assert review(_payload(ctx, []), [], client=FakeBedrock(verdict=warn), model_id="m").status == "warn"


def test_review_accepts_json_in_text(ctx):
    r = review(_payload(ctx, []), [], client=FakeBedrock(text="Here:\n" + json.dumps(PASS)), model_id="m")
    assert r.status == "pass"


@pytest.mark.parametrize(
    "fake",
    [
        FakeBedrock(text="looks fine to me"),
        FakeBedrock(exc=TimeoutError("slow")),
        FakeBedrock(verdict={"status": "maybe"}),
    ],
)
def test_review_fails_closed(ctx, fake):
    assert review(_payload(ctx, []), [], client=fake, model_id="m", required=True).status == "block"
    assert review(_payload(ctx, []), [], client=fake, model_id="m", required=False).status == "warn"


def test_review_disabled_uses_rules_only(ctx):
    r = review(_payload(ctx, []), [Check("arbitrage", "warn", "x")], client=None, enabled=False)
    assert r.status == "warn" and r.claude is None
