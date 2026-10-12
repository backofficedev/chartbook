**What it is.** A first-order autoregression of the 10-year minus 2-year Treasury spread: tomorrow's spread is predicted as a straight-line function of today's. The model file holds two numbers, an intercept and a slope.

**What it is for.** It is here to show how a model is declared and documented, not to forecast. A daily yield spread is so persistent that "tomorrow equals today" is nearly unbeatable, and this model learns almost exactly that.

**How it was trained.** The first 80% of the sample fits the line; the last 20% is held out to compute the scores above.

**Limits.** One lag, one series, no uncertainty estimate, and no account of regime changes. Do not use it for anything that matters.
