# Treasury Curve

The Federal Reserve Board's zero-coupon Treasury yield curve: one row a day since 1961, one column
per maturity from 1 to 30 years. Other pipelines in the tutorial catalog build on it: `rate_outlook`
pins this pipeline's snapshot and reads `treasury_curve:zero_coupon_yields`.

Source: Gurkaynak, Sack and Wright (2007), "The U.S. Treasury Yield Curve: 1961 to the Present",
published by the Federal Reserve Board. A work of the U.S. government, in the public domain.
