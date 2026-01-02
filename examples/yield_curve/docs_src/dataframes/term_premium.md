
**Description:** Term premium measures derived from the U.S. Treasury zero-coupon yield curve. The term premium represents the extra compensation investors require for holding longer-term bonds instead of rolling over short-term bonds.

**Data Source:** Derived from Federal Reserve Board yield curve data

**Columns:**

| Column | Description |
|--------|-------------|
| 10Y 1Y Spread | 10-year yield minus 1-year yield (percentage points) |
| 10Y 2Y Spread | 10-year yield minus 2-year yield (percentage points) |
| 10Y 3Y Spread | 10-year yield minus 3-year yield (percentage points) |

**Methodology:**

These are simple measures of the term premium calculated as yield spreads:

- **10Y-1Y Spread**: SVENY10 - SVENY01
- **10Y-2Y Spread**: SVENY10 - SVENY02
- **10Y-3Y Spread**: SVENY10 - SVENY03

**Interpretation:**

- **Positive spread**: Normal yield curve where long-term rates exceed short-term rates
- **Negative spread**: Inverted yield curve, often associated with recession expectations
- **Steepening**: Increasing spread, may indicate expectations of rising rates or inflation
- **Flattening**: Decreasing spread, may indicate expectations of falling rates or economic slowdown

**Note:** These simple spread measures differ from model-based term premium estimates (such as the Adrian-Crump-Moench model from the NY Fed) which attempt to decompose yields into expected short-term rates and a pure term premium component.

