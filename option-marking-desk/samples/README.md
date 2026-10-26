# Sample data

`nifty_chain_sample.csv`: a synthetic NIFTY chain (114 quotes) in the upload format. The wings have wide spreads, missing bids and stale quotes.

Upload it from the dashboard ("Upload CSV"), or:

```bash
curl -F file=@samples/nifty_chain_sample.csv -F underlying=NIFTY -F spot=24850.0 \
     -F expiry=2026-11-23T15:30:00+05:30 -F as_of=2026-10-24T17:46:30+05:30 \
     http://localhost:8000/chains/upload
```
