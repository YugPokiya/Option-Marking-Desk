"""Models, walk-forward backtest and skill metrics.

Every model is judged against the random walk ("tomorrow's smile = today's"), which is hard to
beat for implied vol. A model is only used if it beats it out of sample.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import RidgeCV
from sklearn.multioutput import MultiOutputRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import FEATURE_COLS, TARGET_COLS
from .surface import GRID_COLS

ALGOS = ("rw", "ridge", "gbr")


class RandomWalk:
    def fit(self, x, y):
        self.n_out = y.shape[1]
        return self

    def predict(self, x):
        return np.zeros((len(x), self.n_out))


def make_model(algo: str):
    if algo == "rw":
        return RandomWalk()
    if algo == "ridge":
        # regularisation picked by efficient leave-one-out CV on the training window only
        return make_pipeline(StandardScaler(), RidgeCV(alphas=np.logspace(-1, 4, 16)))
    if algo == "gbr":
        return MultiOutputRegressor(
            HistGradientBoostingRegressor(
                max_depth=2,
                learning_rate=0.05,
                max_iter=150,
                min_samples_leaf=30,
                l2_regularization=5.0,
                early_stopping=False,
                random_state=0,
            )
        )
    raise ValueError(f"unknown algo {algo}")


def walk_forward(train: pd.DataFrame, algo: str, min_train: int = 200, refit_every: int = 20) -> pd.DataFrame:
    """Expanding-window out-of-sample predictions: fit on [0, i), predict [i, i+refit_every)."""
    x, y = train[FEATURE_COLS].to_numpy(float), train[TARGET_COLS].to_numpy(float)
    preds = np.full_like(y, np.nan)
    for i in range(min_train, len(train), refit_every):
        m = make_model(algo).fit(x[:i], y[:i])
        preds[i : i + refit_every] = m.predict(x[i : i + refit_every])
    out = pd.DataFrame(preds, columns=TARGET_COLS)
    out.insert(0, "date", train["date"].to_numpy())
    return out


@dataclass
class Skill:
    algo: str
    n_test: int
    rmse_vp: dict[str, float] = field(default_factory=dict)  # model RMSE, vol points
    rmse_rw_vp: dict[str, float] = field(default_factory=dict)  # random-walk RMSE, vol points
    skill: dict[str, float] = field(default_factory=dict)  # 1 - rmse/rmse_rw (>0 beats RW)
    hit_rate: dict[str, float] = field(default_factory=dict)  # sign accuracy on moves > 0.1 vp

    @property
    def mean_skill(self) -> float:
        return float(np.mean(list(self.skill.values()))) if self.skill else float("nan")

    def as_dict(self) -> dict:
        return {
            "algo": self.algo,
            "n_test": self.n_test,
            "mean_skill": self.mean_skill,
            "rmse_vp": self.rmse_vp,
            "rmse_rw_vp": self.rmse_rw_vp,
            "skill": self.skill,
            "hit_rate": self.hit_rate,
        }


def score(train: pd.DataFrame, preds: pd.DataFrame, algo: str) -> Skill:
    mask = preds[TARGET_COLS].notna().all(axis=1).to_numpy()
    y, p = train.loc[mask, TARGET_COLS].to_numpy(float), preds.loc[mask, TARGET_COLS].to_numpy(float)
    s = Skill(algo=algo, n_test=int(mask.sum()))
    for j, col in enumerate(GRID_COLS):
        rmse = float(np.sqrt(np.mean((p[:, j] - y[:, j]) ** 2)))
        rmse_rw = float(np.sqrt(np.mean(y[:, j] ** 2)))
        big = np.abs(y[:, j]) > 0.001
        s.rmse_vp[col] = rmse * 100
        s.rmse_rw_vp[col] = rmse_rw * 100
        s.skill[col] = 1 - rmse / rmse_rw if rmse_rw > 0 else 0.0
        s.hit_rate[col] = float(np.mean(np.sign(p[big, j]) == np.sign(y[big, j]))) if big.any() else float("nan")
    return s


def backtest_all(train: pd.DataFrame, algos=ALGOS, **kw) -> dict[str, Skill]:
    return {a: score(train, walk_forward(train, a, **kw), a) for a in algos}


def choose(skills: dict[str, Skill], min_skill: float = 0.02) -> str:
    """Best out-of-sample model, but only if it beats the random walk by a margin; else 'rw'."""
    best = max((a for a in skills if a != "rw"), key=lambda a: skills[a].mean_skill, default="rw")
    return best if skills[best].mean_skill >= min_skill else "rw"


def fit_final(train: pd.DataFrame, algo: str):
    return make_model(algo).fit(train[FEATURE_COLS].to_numpy(float), train[TARGET_COLS].to_numpy(float))


def dumps(model) -> bytes:
    buf = io.BytesIO()
    joblib.dump(model, buf)
    return buf.getvalue()


def loads(blob: bytes):
    # only ever load blobs this app wrote to its own database (joblib = pickle)
    return joblib.load(io.BytesIO(blob))
