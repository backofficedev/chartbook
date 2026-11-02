"""Where a static chart puts its caption, note and source."""

import pandas as pd
import pytest

from chartbook.plotting import ChartConfig, OverlayConfig


@pytest.mark.parametrize("x_title", ["Maturity (years)", "A title\nof two lines"])
def test_the_source_is_below_the_x_axis_title(x_title):
    """It was drawn at a fixed place under the axes, on top of the x-axis title (#166)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from chartbook.plotting.backends._matplotlib import MatplotlibBackend

    df = pd.DataFrame({"maturity": [1, 2, 5, 10, 30], "yield": [4.1, 4.0, 3.9, 4.2, 4.5]})
    config = ChartConfig(chart_type="line", x="maturity", y=["yield"], x_title=x_title, source="Federal Reserve Board")
    fig, ax = MatplotlibBackend()._build_line_figure(df, config, OverlayConfig(), (8, 6))
    try:
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        (note,) = [text for text in fig.texts if "Federal Reserve Board" in text.get_text()]
        assert note.get_window_extent(renderer).y1 <= ax.xaxis.label.get_window_extent(renderer).y0
    finally:
        plt.close(fig)
