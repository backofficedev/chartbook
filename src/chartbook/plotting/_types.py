"""Type definitions for chartbook.plotting."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Sequence

if TYPE_CHECKING:
    import matplotlib.axes
    import matplotlib.figure
    import pandas as pd
    import plotly.graph_objects as go


@dataclass
class ChartConfig:
    """Configuration for a single chart."""

    chart_type: Literal["line", "bar", "scatter", "pie", "area"]
    x: str
    y: list[str]

    # chart_id is optional until save
    chart_id: str | None = None

    # Annotations
    title: str | None = None
    caption: str | None = None
    note: str | None = None
    source: str | None = None

    # Series styling
    color: str | Sequence[str] | None = None
    labels: dict[str, str] | None = None

    # Axis configuration
    x_title: str | None = None
    y_title: str | None = None
    x_range: tuple[float, float] | None = None
    y_range: tuple[float, float] | None = None
    x_tickformat: str | None = None
    y_tickformat: str | None = None

    # Chart-specific
    stacked: bool = False

    # Scatter-specific
    size: str | None = None
    color_by: str | None = None

    # Pie-specific
    names: str | None = None
    values: str | None = None

    # Pass-through for advanced usage
    extra_kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class OverlayConfig:
    """Configuration for chart overlays."""

    nber_recessions: bool = False
    hlines: list[dict[str, Any]] = field(default_factory=list)
    vlines: list[dict[str, Any]] = field(default_factory=list)
    shaded_regions: list[dict[str, Any]] = field(default_factory=list)
    bands: list[dict[str, Any]] = field(default_factory=list)  # Fill between y columns
    regression_line: bool = False


@dataclass
class DualAxisConfig:
    """Configuration for dual-axis charts."""

    x: str
    left_y: list[str]
    right_y: list[str]
    left_type: Literal["line", "bar", "scatter", "area"]
    right_type: Literal["line", "bar", "scatter", "area"]

    # chart_id is optional until save
    chart_id: str | None = None

    # Annotations
    title: str | None = None
    caption: str | None = None
    note: str | None = None
    source: str | None = None

    # Axis titles
    x_title: str | None = None
    left_y_title: str | None = None
    right_y_title: str | None = None

    # Ranges
    left_y_range: tuple[float, float] | None = None
    right_y_range: tuple[float, float] | None = None

    # Tick formatting
    left_y_tickformat: str | None = None
    right_y_tickformat: str | None = None

    # Colors
    left_colors: list[str] | None = None
    right_colors: list[str] | None = None

    # Pass-through for advanced usage
    extra_kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChartResult:
    """Result of creating a chart.

    This object holds the generated figure and provides methods to display
    and save the chart. Call `.show()` to display inline, or `.save(chart_id)`
    to export to multiple formats.

    Attributes
    ----------
    figure : plotly.graph_objects.Figure
        The Plotly figure object. Can be further customized before saving.
    chart_type : str
        The type of chart (line, bar, scatter, pie, area, or dual_*).
    mpl_figure : matplotlib.figure.Figure
        Matplotlib Figure for fine-grained control. Lazily created on first access.
    mpl_axes : matplotlib.axes.Axes
        Matplotlib Axes for fine-grained control. Lazily created on first access.

    Examples
    --------
    >>> result = chartbook.plotting.line(df, x="date", y="gdp")
    >>> result.show()  # Display inline
    >>> result.save(chart_id="gdp_chart")  # Save to files
    >>> print(result.html_path)  # Access saved file path
    """

    figure: "go.Figure"
    chart_type: str

    # Internal state for saving (not shown in repr)
    _config: ChartConfig | DualAxisConfig = field(repr=False)
    _overlay: OverlayConfig = field(repr=False)
    _df: "pd.DataFrame" = field(repr=False)

    # Populated after .save()
    chart_id: str | None = field(default=None)
    output_dir: Path | None = field(default=None)
    html_path: Path | None = field(default=None)
    png_path: Path | None = field(default=None)
    png_wide_path: Path | None = field(default=None)
    pdf_path: Path | None = field(default=None)
    pdf_wide_path: Path | None = field(default=None)

    # Lazy matplotlib objects (private)
    _mpl_figure: "matplotlib.figure.Figure | None" = field(default=None, repr=False)
    _mpl_axes: "matplotlib.axes.Axes | None" = field(default=None, repr=False)

    @property
    def mpl_figure(self) -> "matplotlib.figure.Figure":
        """Access matplotlib Figure for fine-grained control.

        The matplotlib figure is lazily created on first access. You can
        customize it and then call `.save()` to export with your changes.

        Returns
        -------
        matplotlib.figure.Figure
            The matplotlib Figure object.

        Examples
        --------
        >>> result = chartbook.plotting.line(df, x="date", y="gdp")
        >>> fig = result.mpl_figure
        >>> fig.suptitle("Custom Title", fontsize=16)
        >>> result.save(chart_id="custom_chart")
        """
        if self._mpl_figure is None:
            self._create_mpl_objects()
        return self._mpl_figure  # type: ignore[return-value]

    @property
    def mpl_axes(self) -> "matplotlib.axes.Axes":
        """Access matplotlib Axes for fine-grained control.

        The matplotlib axes is lazily created on first access. You can
        customize it and then call `.save()` to export with your changes.

        Returns
        -------
        matplotlib.axes.Axes
            The matplotlib Axes object.

        Examples
        --------
        >>> result = chartbook.plotting.line(df, x="date", y="gdp")
        >>> ax = result.mpl_axes
        >>> ax.axhline(y=100, color='red', linestyle='--', label='Target')
        >>> ax.legend()
        >>> result.save(chart_id="annotated_chart")
        """
        if self._mpl_axes is None:
            self._create_mpl_objects()
        return self._mpl_axes  # type: ignore[return-value]

    def _create_mpl_objects(self) -> None:
        """Lazily create matplotlib figure and axes."""
        from chartbook.plotting.backends import get_backend

        backend = get_backend("matplotlib")
        self._mpl_figure, self._mpl_axes = backend.build_figure(
            self._df, self._config, self._overlay
        )

    def show(self) -> "ChartResult":
        """Display the figure inline.

        Uses Plotly's interactive display. In Jupyter notebooks, this will
        render the chart directly in the output cell.

        Returns
        -------
        ChartResult
            Self, for method chaining and Jupyter display.

        Examples
        --------
        >>> result = chartbook.plotting.line(df, x="date", y="gdp")
        >>> result.show()
        """
        self.figure.show()
        return self

    def _repr_html_(self) -> str:
        """Return HTML representation for Jupyter notebook display.

        This method is called automatically by Jupyter when displaying
        the object, enabling inline rendering of the Plotly figure.
        """
        return self.figure.to_html(include_plotlyjs="cdn", full_html=False)

    def save(
        self,
        chart_id: str,
        output_dir: str | Path | None = None,
        interactive: bool = True,
    ) -> "ChartResult":
        """Save the chart to multiple formats.

        Generates up to 5 files:
        - `{chart_id}.html` - Interactive Plotly chart (if interactive=True)
        - `{chart_id}.png` - Static PNG (8×6")
        - `{chart_id}_wide.png` - Static PNG wide format (12×6")
        - `{chart_id}.pdf` - Static PDF (8×6")
        - `{chart_id}_wide.pdf` - Static PDF wide format (12×6")

        Parameters
        ----------
        chart_id : str
            Unique identifier for the chart. Used in filenames and for
            linking to chartbook.toml.
        output_dir : str | Path, optional
            Directory to save files. Default: global config default_output_dir.
        interactive : bool, default True
            Whether to generate interactive HTML file.

        Returns
        -------
        ChartResult
            Self, for method chaining.

        Examples
        --------
        >>> result = chartbook.plotting.line(df, x="date", y="gdp")
        >>> result.save(chart_id="gdp_chart")
        >>> print(result.html_path)
        ./_output/gdp_chart.html

        >>> # Method chaining
        >>> paths = chartbook.plotting.line(df, x="date", y="gdp").save("gdp").paths
        """
        from chartbook.plotting._output import save_chart_from_result
        from chartbook.plotting._validation import validate_chart_id

        validate_chart_id(chart_id)
        self.chart_id = chart_id

        save_chart_from_result(self, output_dir, interactive)
        return self

    @property
    def paths(self) -> dict[str, Path]:
        """Get all saved file paths as a dictionary.

        Returns an empty dict if `.save()` has not been called yet.

        Returns
        -------
        dict[str, Path]
            Mapping of format name to file path.
            Keys: 'html', 'png', 'png_wide', 'pdf', 'pdf_wide'

        Examples
        --------
        >>> result = chartbook.plotting.line(df, x="date", y="gdp")
        >>> result.paths  # Empty before save
        {}
        >>> result.save(chart_id="gdp")
        >>> result.paths
        {'html': Path('./_output/gdp.html'), 'png': Path('./_output/gdp.png'), ...}
        """
        if self.chart_id is None:
            return {}
        result: dict[str, Path] = {}
        if self.html_path:
            result["html"] = self.html_path
        if self.png_path:
            result["png"] = self.png_path
        if self.png_wide_path:
            result["png_wide"] = self.png_wide_path
        if self.pdf_path:
            result["pdf"] = self.pdf_path
        if self.pdf_wide_path:
            result["pdf_wide"] = self.pdf_wide_path
        return result

    def __repr__(self) -> str:
        if self.chart_id:
            paths_str = ", ".join(f"{k}={v}" for k, v in self.paths.items())
            return f"ChartResult({self.chart_id}: {paths_str})"
        return f"ChartResult({self.chart_type}, unsaved)"
