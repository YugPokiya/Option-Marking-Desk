"""Next-day implied-vol forecasting from NSE end-of-day data.

Pipeline: bhavcopy -> daily SVI fits -> 30-day constant-maturity smile on a moneyness grid
-> features -> ML forecast of tomorrow's smile -> rule checks + Claude review -> publish.
"""
