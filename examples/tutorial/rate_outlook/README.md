# Rate Outlook

A pipeline that builds on two others. It never reads their folders: it pins their snapshots in
`chartbook.lock`, and reads their dataframes by name,

```python
curve = data.load("treasury_curve:zero_coupon_yields")
macro = data.load("macro_basics:macro_series")
```

so its numbers do not change until `chartbook update` moves a pin. It derives the term spread,
charts it beside the unemployment rate, and fits a small model to it, whose page names the exact
snapshot of the yield curve it was trained on.
