# Methodology

This page describes the methodology used in the yield curve analysis pipeline.

## Data Collection

Treasury yield curve data is sourced from the Federal Reserve Board's
[FEDS 200628](https://www.federalreserve.gov/data/yield-curve-tables/feds200628.csv)
dataset, which provides daily zero-coupon yield estimates.

## Yield Curve Construction

The zero-coupon yields are estimated using the Svensson (1994) parametric model,
which fits a smooth curve through observed Treasury security prices. The model
produces continuous yield estimates for maturities from 1 to 30 years.

## Term Premium Decomposition

Term premium is computed as the difference between observed yields at different
maturities. For example, the 10Y-1Y term premium is the 10-year yield minus the
1-year yield. This spread reflects the compensation investors demand for holding
longer-duration bonds.
