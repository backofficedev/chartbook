import numpy as np
import pandas as pd

import chartbook
from chartbook import data

rng = np.random.default_rng(seed=42)
df = pd.DataFrame({
    "date": pd.date_range("2024-01-01", periods=365, freq="D"),
    "walk_a": rng.standard_normal(365).cumsum() + 100,
    "walk_b": rng.standard_normal(365).cumsum() + 100,
})
df.to_parquet(data.path("walks"))  # chartbook.toml says where "walks" goes

chartbook.plotting.line(
    df, x="date", y=["walk_a", "walk_b"], title="Two Random Walks",
).save(chart_id="random_walks", output_dir="_output")
