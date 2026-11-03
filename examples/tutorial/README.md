# The tutorial's pipelines

The three pipelines the [Explore a Catalog](../../docs_src/tutorials/explore-a-catalog.md) tutorial
downloads, as a store of their snapshots:

| Pipeline | What it makes | From |
|---|---|---|
| `treasury_curve` | the zero-coupon Treasury yield curve, and two charts of it | the Federal Reserve Board |
| `macro_basics` | unemployment, CPI inflation, payrolls and real GDP growth, and two charts | BLS and BEA, through FRED |
| `rate_outlook` | the term spread, a model of it and a chart, built on the other two, pinned | the two pipelines above |

Every series is a work of the U.S. government, in the public domain. `make_store.py` builds the
store and the zip attached to each release; its docstring says how.
