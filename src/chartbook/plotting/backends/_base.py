"""Base protocol and abstract class for plotting backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import pandas as pd

    from chartbook.plotting._types import ChartConfig, DualAxisConfig, OverlayConfig


@runtime_checkable
class PlottingBackend(Protocol):
    """Protocol for plotting backends.

    Third-party backends must implement this protocol to be compatible
    with chartbook.plotting.
    """

    @property
    def name(self) -> str:
        """Backend name (e.g., 'plotly', 'altair')."""
        ...

    def create_line(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a line chart."""
        ...

    def create_bar(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a bar chart."""
        ...

    def create_scatter(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a scatter chart."""
        ...

    def create_pie(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a pie chart."""
        ...

    def create_area(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create an area chart."""
        ...

    def create_dual_axis(
        self,
        df: "pd.DataFrame",
        config: "DualAxisConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a dual-axis chart."""
        ...


class BaseBackend(ABC):
    """Abstract base class for plotting backends with common utilities."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend name."""

    @abstractmethod
    def create_line(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a line chart."""

    @abstractmethod
    def create_bar(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a bar chart."""

    @abstractmethod
    def create_scatter(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a scatter chart."""

    @abstractmethod
    def create_pie(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a pie chart."""

    @abstractmethod
    def create_area(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create an area chart."""

    def create_dual_axis(
        self,
        df: "pd.DataFrame",
        config: "DualAxisConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a dual-axis chart.

        Default implementation raises NotImplementedError.
        """
        raise NotImplementedError(
            f"Dual-axis charts not supported by {self.name} backend"
        )

    def create_chart(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Route to appropriate chart creation method based on chart_type."""
        chart_type = config.chart_type

        if chart_type == "line":
            self.create_line(df, config, overlay, output_path, size)
        elif chart_type == "bar":
            self.create_bar(df, config, overlay, output_path, size)
        elif chart_type == "scatter":
            self.create_scatter(df, config, overlay, output_path, size)
        elif chart_type == "pie":
            self.create_pie(df, config, overlay, output_path, size)
        elif chart_type == "area":
            self.create_area(df, config, overlay, output_path, size)
        else:
            raise ValueError(f"Unknown chart type: {chart_type}")
