"""Global configuration for chartbook.plotting."""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class PlottingConfig:
    """Global configuration for chartbook.plotting."""

    # Default output settings
    default_output_dir: Path = field(default_factory=lambda: Path("./_output"))
    default_interactive: bool = True

    # Default backend
    default_backend: Literal["plotly", "matplotlib"] = "plotly"

    # Overlay defaults
    nber_recessions: bool = False

    # Style settings
    matplotlib_style: str | Path = "chartbook"
    plotly_template: str = "plotly_white"

    # Figure sizes
    figure_size_single: tuple[float, float] = (8, 6)
    figure_size_wide: tuple[float, float] = (12, 6)

    # Color palette (default Plotly/D3 colors)
    color_palette: list[str] = field(
        default_factory=lambda: [
            "#1f77b4",
            "#ff7f0e",
            "#2ca02c",
            "#d62728",
            "#9467bd",
            "#8c564b",
            "#e377c2",
            "#7f7f7f",
            "#bcbd22",
            "#17becf",
        ]
    )


# Global config instance
_config = PlottingConfig()


def configure(
    *,
    default_output_dir: str | Path | None = None,
    default_interactive: bool | None = None,
    default_backend: Literal["plotly", "matplotlib"] | None = None,
    nber_recessions: bool | None = None,
    matplotlib_style: str | Path | None = None,
    plotly_template: str | None = None,
    figure_size_single: tuple[float, float] | None = None,
    figure_size_wide: tuple[float, float] | None = None,
    color_palette: list[str] | None = None,
) -> None:
    """Configure global plotting defaults.

    Parameters
    ----------
    default_output_dir : str | Path, optional
        Default directory for saving charts.
    default_interactive : bool, optional
        Whether to generate interactive HTML by default.
    default_backend : str, optional
        Default backend: "plotly" or "matplotlib".
    nber_recessions : bool, optional
        Whether to show NBER recession shading by default.
    matplotlib_style : str | Path, optional
        Matplotlib style name or path to .mplstyle file.
    plotly_template : str, optional
        Plotly template name (e.g., "plotly_white", "ggplot2").
    figure_size_single : tuple, optional
        Default figure size for single format (width, height) in inches.
    figure_size_wide : tuple, optional
        Default figure size for wide format (width, height) in inches.
    color_palette : list[str], optional
        List of hex colors for the default color cycle.

    Examples
    --------
    >>> import chartbook
    >>> chartbook.plotting.configure(
    ...     default_output_dir="./_charts",
    ...     nber_recessions=True,
    ...     matplotlib_style="seaborn-v0_8-whitegrid",
    ... )
    """
    global _config

    if default_output_dir is not None:
        _config.default_output_dir = Path(default_output_dir)
    if default_interactive is not None:
        _config.default_interactive = default_interactive
    if default_backend is not None:
        _config.default_backend = default_backend
    if nber_recessions is not None:
        _config.nber_recessions = nber_recessions
    if matplotlib_style is not None:
        _config.matplotlib_style = matplotlib_style
    if plotly_template is not None:
        _config.plotly_template = plotly_template
    if figure_size_single is not None:
        _config.figure_size_single = figure_size_single
    if figure_size_wide is not None:
        _config.figure_size_wide = figure_size_wide
    if color_palette is not None:
        _config.color_palette = color_palette


def get_config() -> PlottingConfig:
    """Get current global plotting configuration."""
    return _config


def set_style(style: str | Path) -> None:
    """Set the matplotlib stylesheet.

    Parameters
    ----------
    style : str | Path
        Either a built-in style name (e.g., "seaborn-v0_8-whitegrid"),
        "chartbook" for the bundled style, or path to a .mplstyle file.

    Examples
    --------
    >>> chartbook.plotting.set_style("chartbook")
    >>> chartbook.plotting.set_style("seaborn-v0_8-whitegrid")
    >>> chartbook.plotting.set_style("./my_custom_style.mplstyle")
    """
    global _config
    _config.matplotlib_style = style

    # Apply immediately if matplotlib is available
    try:
        import matplotlib.pyplot as plt

        if style == "chartbook":
            style_path = get_bundled_style_path()
            plt.style.use(str(style_path))
        elif isinstance(style, Path) or (
            isinstance(style, str) and style.endswith(".mplstyle")
        ):
            plt.style.use(str(style))
        else:
            plt.style.use(style)
    except ImportError:
        pass  # matplotlib not installed, style will be applied when needed


def get_bundled_style_path() -> Path:
    """Get path to bundled chartbook.mplstyle."""
    package_files = importlib.resources.files("chartbook")
    return Path(str(package_files)) / "plotting" / "styles" / "chartbook.mplstyle"


def apply_matplotlib_style() -> None:
    """Apply the configured matplotlib style."""
    import matplotlib.pyplot as plt

    style = _config.matplotlib_style

    if style == "chartbook":
        style_path = get_bundled_style_path()
        if style_path.exists():
            plt.style.use(str(style_path))
        else:
            # Fallback if style file doesn't exist yet
            plt.style.use("seaborn-v0_8-whitegrid")
    elif isinstance(style, Path) or (
        isinstance(style, str) and style.endswith(".mplstyle")
    ):
        plt.style.use(str(style))
    else:
        plt.style.use(style)
