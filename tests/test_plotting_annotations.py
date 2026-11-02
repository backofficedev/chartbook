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


def test_a_dual_axis_chart_has_its_caption_note_and_source():
    """They were taken and never drawn."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from chartbook.plotting import DualAxisConfig
    from chartbook.plotting.backends._matplotlib import MatplotlibBackend

    df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=4, freq="MS"), "a": [1, 2, 3, 4], "b": [9, 8, 7, 6]})
    config = DualAxisConfig(x="date", left_y=["a"], right_y=["b"], left_type="line", right_type="line", x_title="Month", caption="C", note="N", source="Fed")
    fig, ax = MatplotlibBackend()._build_dual_axis_figure(df, config, OverlayConfig(), (8, 6))
    try:
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        (said,) = [text for text in fig.texts if "Source: Fed" in text.get_text()]
        assert "Note: N" in said.get_text() and said.get_text().startswith("C")
        assert said.get_window_extent(renderer).y1 <= ax.xaxis.label.get_window_extent(renderer).y0
    finally:
        plt.close(fig)
