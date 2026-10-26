import math

from fastapi import APIRouter

from ..quant import black
from ..schemas import PriceIn, PriceOut

router = APIRouter(tags=["pricing"])


@router.post("/price", response_model=PriceOut, summary="Black-76 price for one option")
async def price(p: PriceIn) -> PriceOut:
    t = p.days / 365.0
    df = math.exp(-p.rate * t)
    fwd = p.spot * math.exp((p.rate - p.div_yield) * t)
    is_call = p.option_type == "C"
    return PriceOut(
        price=float(black.price(fwd, p.strike, t, p.vol, df, is_call)),
        forward=fwd,
        delta=float(black.delta(fwd, p.strike, t, p.vol, df, is_call)),
        vega_per_vol_point=float(black.vega(fwd, p.strike, t, p.vol, df)) / 100,
        intrinsic=float(black.intrinsic(fwd, p.strike, df, is_call)),
    )
