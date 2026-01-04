"""Output file management for chartbook.plotting."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from chartbook.plotting._config import get_config
from chartbook.plotting._types import ChartResult

if TYPE_CHECKING:
    import pandas as pd

    from chartbook.plotting._types import ChartConfig, DualAxisConfig, OverlayConfig


def create_chart_result(
    df: "pd.DataFrame",
    config: "ChartConfig",
    overlay: "OverlayConfig",
) -> ChartResult:
    """Create a ChartResult with the Plotly figure.

    This is the main entry point for creating charts. It builds the Plotly
    figure and returns a ChartResult that can be displayed or saved.

    Parameters
    ----------
    df : DataFrame
        Data to plot.
    config : ChartConfig
        Chart configuration.
    overlay : OverlayConfig
        Overlay configuration.

    Returns
    -------
    ChartResult
        Object containing the figure and methods to display/save.
    """
    from chartbook.plotting.backends import get_backend

    global_config = get_config()
    plotly_backend = get_backend("plotly")
    size = global_config.figure_size_single

    # Build the Plotly figure based on chart type
    if config.chart_type == "line":
        figure = plotly_backend.build_line(df, config, overlay, size)
    elif config.chart_type == "bar":
        figure = plotly_backend.build_bar(df, config, overlay, size)
    elif config.chart_type == "scatter":
        figure = plotly_backend.build_scatter(df, config, overlay, size)
    elif config.chart_type == "pie":
        figure = plotly_backend.build_pie(df, config, overlay, size)
    elif config.chart_type == "area":
        figure = plotly_backend.build_area(df, config, overlay, size)
    else:
        raise ValueError(f"Unknown chart type: {config.chart_type}")

    return ChartResult(
        figure=figure,
        chart_type=config.chart_type,
        _config=config,
        _overlay=overlay,
        _df=df,
    )


def create_dual_chart_result(
    df: "pd.DataFrame",
    config: "DualAxisConfig",
    overlay: "OverlayConfig",
) -> ChartResult:
    """Create a ChartResult for a dual-axis chart.

    Parameters
    ----------
    df : DataFrame
        Data to plot.
    config : DualAxisConfig
        Dual-axis chart configuration.
    overlay : OverlayConfig
        Overlay configuration.

    Returns
    -------
    ChartResult
        Object containing the figure and methods to display/save.
    """
    from chartbook.plotting.backends import get_backend

    global_config = get_config()
    plotly_backend = get_backend("plotly")
    size = global_config.figure_size_single

    figure = plotly_backend.build_dual_axis(df, config, overlay, size)

    return ChartResult(
        figure=figure,
        chart_type=f"dual_{config.left_type}_{config.right_type}",
        _config=config,
        _overlay=overlay,
        _df=df,
    )


def save_chart_from_result(
    result: ChartResult,
    output_dir: str | Path | None = None,
    interactive: bool = True,
) -> None:
    """Save a ChartResult to multiple formats.

    This is called by ChartResult.save() to do the actual file generation.
    It modifies the result in-place, populating the path attributes.

    Parameters
    ----------
    result : ChartResult
        The chart result to save. Must have chart_id set.
    output_dir : str | Path, optional
        Directory to save files. Default: global config default_output_dir.
    interactive : bool
        Whether to generate interactive HTML.
    """
    from chartbook.plotting._types import DualAxisConfig
    from chartbook.plotting.backends import get_backend

    global_config = get_config()
    chart_id = result.chart_id

    if chart_id is None:
        raise ValueError("chart_id must be set before saving")

    # Determine output directory
    if output_dir is None:
        out_dir = global_config.default_output_dir
    else:
        out_dir = Path(output_dir)

    out_dir.mkdir(parents=True, exist_ok=True)
    result.output_dir = out_dir

    config = result._config
    overlay = result._overlay
    df = result._df

    # Check if this is a dual-axis chart
    is_dual = isinstance(config, DualAxisConfig)

    # Generate interactive HTML (Plotly) - use the existing figure
    # Note: No explicit dimensions set to enable responsive behavior in browser
    if interactive:
        html_path = out_dir / f"{chart_id}.html"
        result.figure.write_html(str(html_path), include_plotlyjs="cdn")
        result.html_path = html_path

    # Generate static formats (Matplotlib)
    matplotlib_backend = get_backend("matplotlib")

    # PNG single format
    png_path = out_dir / f"{chart_id}.png"
    if is_dual:
        matplotlib_backend.create_dual_axis(
            df, config, overlay, png_path, global_config.figure_size_single
        )
    else:
        matplotlib_backend.create_chart(
            df, config, overlay, png_path, global_config.figure_size_single
        )
    result.png_path = png_path

    # PNG wide format
    png_wide_path = out_dir / f"{chart_id}_wide.png"
    if is_dual:
        matplotlib_backend.create_dual_axis(
            df, config, overlay, png_wide_path, global_config.figure_size_wide
        )
    else:
        matplotlib_backend.create_chart(
            df, config, overlay, png_wide_path, global_config.figure_size_wide
        )
    result.png_wide_path = png_wide_path

    # PDF single format
    pdf_path = out_dir / f"{chart_id}.pdf"
    if is_dual:
        matplotlib_backend.create_dual_axis(
            df, config, overlay, pdf_path, global_config.figure_size_single
        )
    else:
        matplotlib_backend.create_chart(
            df, config, overlay, pdf_path, global_config.figure_size_single
        )
    result.pdf_path = pdf_path

    # PDF wide format
    pdf_wide_path = out_dir / f"{chart_id}_wide.pdf"
    if is_dual:
        matplotlib_backend.create_dual_axis(
            df, config, overlay, pdf_wide_path, global_config.figure_size_wide
        )
    else:
        matplotlib_backend.create_chart(
            df, config, overlay, pdf_wide_path, global_config.figure_size_wide
        )
    result.pdf_wide_path = pdf_wide_path
