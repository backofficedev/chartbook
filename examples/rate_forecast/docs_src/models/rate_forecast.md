**What it is.** A first-order autoregression of the 10-year zero-coupon Treasury yield: tomorrow's yield is predicted as a straight-line function of today's. The model file holds two numbers, an intercept and a slope.

**What it is for.** It is here to show a model in one pipeline trained on data from another, not to forecast. A daily yield is so persistent that "tomorrow equals today" is nearly unbeatable, and this model learns almost exactly that.

**What it was trained on.** The `fed_yield_curve` dataframe of the Yield Curve pipeline, which this pipeline declares as a dependency and pins. The copy it read is named by its hash in `chartbook.lock`, and in this model's record in `index.json` under `pinned_inputs`. It stays the same until someone runs `chartbook update`.

**How it was trained.** The first 80% of the sample fits the line; the last 20% is held out to compute the scores above.

**Limits.** One lag, one series, no uncertainty estimate, and no account of regime changes. Do not use it for anything that matters.
