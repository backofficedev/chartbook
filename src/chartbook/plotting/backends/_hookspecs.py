"""Pluggy hook specifications for chartbook.plotting backends."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pluggy

if TYPE_CHECKING:
    import pandas as pd

    from chartbook.plotting._types import ChartConfig, DualAxisConfig, OverlayConfig

hookspec = pluggy.HookspecMarker("chartbook_plotting")
hookimpl = pluggy.HookimplMarker("chartbook_plotting")


class PlottingHookSpec:
    """Hook specifications for chartbook.plotting backends.

    Third-party packages can implement these hooks to provide custom
    plotting backends. Register via entry points:

        [project.entry-points.chartbook_plotting]
        my_backend = "mypackage.backend:MyBackend"
    """

    @hookspec
    def chartbook_get_backend_name(self) -> str:
        """Return the name of this backend (e.g., "plotly", "altair").

        Returns
        -------
        str
            The backend name used for identification.
        """

    @hookspec
    def chartbook_create_line(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a line chart.

        Parameters
        ----------
        df : DataFrame
            Data to plot.
        config : ChartConfig
            Chart configuration (columns, titles, formatting).
        overlay : OverlayConfig
            Overlay configuration (recession bars, hlines, etc.).
        output_path : Path
            Path to save the output file.
        size : tuple
            Figure size as (width, height) in inches.
        """

    @hookspec
    def chartbook_create_bar(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a bar chart."""

    @hookspec
    def chartbook_create_scatter(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a scatter chart."""

    @hookspec
    def chartbook_create_pie(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a pie chart."""

    @hookspec
    def chartbook_create_area(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create an area chart."""

    @hookspec
    def chartbook_create_dual_axis(
        self,
        df: "pd.DataFrame",
        config: "DualAxisConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a dual-axis chart."""
