"""Matplotlib backend for static chart output."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from chartbook.plotting._config import apply_matplotlib_style, get_config
from chartbook.plotting.backends._base import BaseBackend

if TYPE_CHECKING:
    import matplotlib.axes
    import matplotlib.figure
    import pandas as pd

    from chartbook.plotting._types import ChartConfig, DualAxisConfig, OverlayConfig


class MatplotlibBackend(BaseBackend):
    """Matplotlib backend for creating static charts (PNG, PDF, EPS)."""

    @property
    def name(self) -> str:
        return "matplotlib"

    def build_figure(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig | DualAxisConfig",
        overlay: "OverlayConfig",
    ) -> tuple["matplotlib.figure.Figure", "matplotlib.axes.Axes"]:
        """Build a matplotlib figure and axes for the given chart config.

        This is used by ChartResult.mpl_figure and ChartResult.mpl_axes for
        lazy access to matplotlib objects for fine-grained customization.

        Parameters
        ----------
        df : DataFrame
            Data to plot.
        config : ChartConfig | DualAxisConfig
            Chart configuration.
        overlay : OverlayConfig
            Overlay configuration.

        Returns
        -------
        tuple[Figure, Axes]
            The matplotlib Figure and Axes objects.
        """
        from chartbook.plotting._types import DualAxisConfig

        size = get_config().figure_size_single

        if isinstance(config, DualAxisConfig):
            return self._build_dual_axis_figure(df, config, overlay, size)

        # Dispatch to appropriate build method based on chart type
        if config.chart_type == "line":
            return self._build_line_figure(df, config, overlay, size)
        elif config.chart_type == "bar":
            return self._build_bar_figure(df, config, overlay, size)
        elif config.chart_type == "scatter":
            return self._build_scatter_figure(df, config, overlay, size)
        elif config.chart_type == "pie":
            return self._build_pie_figure(df, config, overlay, size)
        elif config.chart_type == "area":
            return self._build_area_figure(df, config, overlay, size)
        else:
            raise ValueError(f"Unknown chart type: {config.chart_type}")

    def _setup_figure(
        self, size: tuple[float, float]
    ) -> tuple["matplotlib.figure.Figure", "matplotlib.axes.Axes"]:
        """Create and configure a matplotlib figure."""
        import matplotlib.pyplot as plt

        apply_matplotlib_style()
        fig, ax = plt.subplots(figsize=size)
        return fig, ax

    def _apply_config(self, ax: "matplotlib.axes.Axes", config: "ChartConfig") -> None:
        """Apply chart configuration to axes."""
        if config.title:
            ax.set_title(config.title)
        if config.x_title:
            ax.set_xlabel(config.x_title)
        if config.y_title:
            ax.set_ylabel(config.y_title)
        if config.x_range:
            ax.set_xlim(config.x_range)
        if config.y_range:
            ax.set_ylim(config.y_range)

    def _apply_overlays(
        self,
        ax: "matplotlib.axes.Axes",
        overlay: "OverlayConfig",
        df: "pd.DataFrame",
        x_col: str,
    ) -> None:
        """Apply overlays to the axes."""
        from chartbook.plotting._overlays import apply_overlays_matplotlib

        apply_overlays_matplotlib(ax, overlay, df, x_col)

    def _add_annotations(
        self,
        fig: "matplotlib.figure.Figure",
        ax: "matplotlib.axes.Axes",
        config: "ChartConfig",
    ) -> None:
        """Add caption, note, and source annotations."""
        annotations = []
        if config.caption:
            annotations.append(config.caption)
        if config.note:
            annotations.append(f"Note: {config.note}")
        if config.source:
            annotations.append(f"Source: {config.source}")

        if annotations:
            annotation_text = "\n".join(annotations)
            fig.text(
                0.5,
                -0.05,
                annotation_text,
                ha="center",
                va="top",
                fontsize=9,
                transform=ax.transAxes,
                wrap=True,
            )

    def _save_figure(self, fig: "matplotlib.figure.Figure", output_path: Path) -> None:
        """Save figure to file."""
        import matplotlib.pyplot as plt

        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight", dpi=300)
        plt.close(fig)

    def _get_colors(self, config: "ChartConfig", n_series: int) -> list[str]:
        """Get colors for the chart series."""
        if config.color:
            if isinstance(config.color, str):
                return [config.color] * n_series
            return list(config.color)[:n_series]
        return get_config().color_palette[:n_series]

    def _build_line_figure(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        size: tuple[float, float],
    ) -> tuple["matplotlib.figure.Figure", "matplotlib.axes.Axes"]:
        """Build a line chart figure without saving."""
        fig, ax = self._setup_figure(size)
        colors = self._get_colors(config, len(config.y))

        for i, y_col in enumerate(config.y):
            label = config.labels.get(y_col, y_col) if config.labels else y_col
            ax.plot(df[config.x], df[y_col], label=label, color=colors[i])

        if len(config.y) > 1:
            ax.legend()

        self._apply_config(ax, config)
        self._apply_overlays(ax, overlay, df, config.x)
        self._add_annotations(fig, ax, config)
        return fig, ax

    def create_line(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a line chart and save to file."""
        fig, ax = self._build_line_figure(df, config, overlay, size)
        self._save_figure(fig, output_path)

    def _build_bar_figure(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        size: tuple[float, float],
    ) -> tuple["matplotlib.figure.Figure", "matplotlib.axes.Axes"]:
        """Build a bar chart figure without saving."""
        import numpy as np

        fig, ax = self._setup_figure(size)
        colors = self._get_colors(config, len(config.y))

        x = np.arange(len(df))
        width = 0.8 / len(config.y) if not config.stacked else 0.8

        bottom = np.zeros(len(df)) if config.stacked else None

        for i, y_col in enumerate(config.y):
            label = config.labels.get(y_col, y_col) if config.labels else y_col

            if config.stacked:
                ax.bar(x, df[y_col], width, label=label, color=colors[i], bottom=bottom)
                bottom = bottom + df[y_col].values
            else:
                offset = (i - len(config.y) / 2 + 0.5) * width
                ax.bar(x + offset, df[y_col], width, label=label, color=colors[i])

        # Set x-tick labels
        ax.set_xticks(x)
        ax.set_xticklabels(df[config.x], rotation=45, ha="right")

        if len(config.y) > 1:
            ax.legend()

        self._apply_config(ax, config)
        self._apply_overlays(ax, overlay, df, config.x)
        self._add_annotations(fig, ax, config)
        return fig, ax

    def create_bar(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a bar chart and save to file."""
        fig, ax = self._build_bar_figure(df, config, overlay, size)
        self._save_figure(fig, output_path)

    def _build_scatter_figure(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        size: tuple[float, float],
    ) -> tuple["matplotlib.figure.Figure", "matplotlib.axes.Axes"]:
        """Build a scatter chart figure without saving."""
        fig, ax = self._setup_figure(size)

        y_col = config.y[0]  # Scatter uses first y column

        # Handle size mapping
        sizes = None
        if config.size and config.size in df.columns:
            sizes = df[config.size]
            # Normalize sizes to reasonable marker sizes
            sizes = (sizes - sizes.min()) / (sizes.max() - sizes.min()) * 200 + 20

        # Handle color by category
        if config.color_by and config.color_by in df.columns:
            categories = df[config.color_by].unique()
            colors = get_config().color_palette[: len(categories)]
            for cat, color in zip(categories, colors):
                mask = df[config.color_by] == cat
                cat_sizes = sizes[mask] if sizes is not None else None
                ax.scatter(
                    df.loc[mask, config.x],
                    df.loc[mask, y_col],
                    s=cat_sizes,
                    c=color,
                    label=str(cat),
                    alpha=0.7,
                )
            ax.legend()
        else:
            color = self._get_colors(config, 1)[0]
            ax.scatter(df[config.x], df[y_col], s=sizes, c=color, alpha=0.7)

        self._apply_config(ax, config)
        self._apply_overlays(ax, overlay, df, config.x)
        self._add_annotations(fig, ax, config)
        return fig, ax

    def create_scatter(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a scatter chart and save to file."""
        fig, ax = self._build_scatter_figure(df, config, overlay, size)
        self._save_figure(fig, output_path)

    def _build_pie_figure(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        size: tuple[float, float],
    ) -> tuple["matplotlib.figure.Figure", "matplotlib.axes.Axes"]:
        """Build a pie chart figure without saving."""
        fig, ax = self._setup_figure(size)

        names_col = config.names or config.x
        values_col = config.values or config.y[0]

        colors = get_config().color_palette[: len(df)]
        wedges, texts, autotexts = ax.pie(
            df[values_col],
            labels=df[names_col],
            colors=colors,
            autopct="%1.1f%%",
            startangle=90,
        )

        ax.axis("equal")

        if config.title:
            ax.set_title(config.title)

        self._add_annotations(fig, ax, config)
        return fig, ax

    def create_pie(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a pie chart and save to file."""
        fig, ax = self._build_pie_figure(df, config, overlay, size)
        self._save_figure(fig, output_path)

    def _build_area_figure(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        size: tuple[float, float],
    ) -> tuple["matplotlib.figure.Figure", "matplotlib.axes.Axes"]:
        """Build an area chart figure without saving."""
        fig, ax = self._setup_figure(size)
        colors = self._get_colors(config, len(config.y))

        if config.stacked:
            ax.stackplot(
                df[config.x],
                [df[y_col] for y_col in config.y],
                labels=[
                    config.labels.get(y, y) if config.labels else y for y in config.y
                ],
                colors=colors,
                alpha=0.7,
            )
        else:
            for i, y_col in enumerate(config.y):
                label = config.labels.get(y_col, y_col) if config.labels else y_col
                ax.fill_between(
                    df[config.x], df[y_col], alpha=0.5, label=label, color=colors[i]
                )
                ax.plot(df[config.x], df[y_col], color=colors[i])

        if len(config.y) > 1:
            ax.legend()

        self._apply_config(ax, config)
        self._apply_overlays(ax, overlay, df, config.x)
        self._add_annotations(fig, ax, config)
        return fig, ax

    def create_area(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create an area chart and save to file."""
        fig, ax = self._build_area_figure(df, config, overlay, size)
        self._save_figure(fig, output_path)

    def _build_dual_axis_figure(
        self,
        df: "pd.DataFrame",
        config: "DualAxisConfig",
        overlay: "OverlayConfig",
        size: tuple[float, float],
    ) -> tuple["matplotlib.figure.Figure", "matplotlib.axes.Axes"]:
        """Build a dual-axis chart figure without saving."""
        fig, ax1 = self._setup_figure(size)
        ax2 = ax1.twinx()

        left_colors = (
            config.left_colors or get_config().color_palette[: len(config.left_y)]
        )
        right_colors = (
            config.right_colors
            or get_config().color_palette[
                len(config.left_y) : len(config.left_y) + len(config.right_y)
            ]
        )

        # Plot left axis
        self._plot_series_on_axis(
            ax1, df, config.x, config.left_y, config.left_type, left_colors
        )

        # Plot right axis
        self._plot_series_on_axis(
            ax2, df, config.x, config.right_y, config.right_type, right_colors
        )

        # Configure axes
        if config.title:
            ax1.set_title(config.title)
        if config.x_title:
            ax1.set_xlabel(config.x_title)
        if config.left_y_title:
            ax1.set_ylabel(config.left_y_title)
        if config.right_y_title:
            ax2.set_ylabel(config.right_y_title)
        if config.left_y_range:
            ax1.set_ylim(config.left_y_range)
        if config.right_y_range:
            ax2.set_ylim(config.right_y_range)

        # Combine legends
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="best")

        # Apply overlays to left axis
        from chartbook.plotting._overlays import apply_overlays_matplotlib

        apply_overlays_matplotlib(ax1, overlay, df, config.x)

        return fig, ax1

    def create_dual_axis(
        self,
        df: "pd.DataFrame",
        config: "DualAxisConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a dual-axis chart and save to file."""
        fig, ax = self._build_dual_axis_figure(df, config, overlay, size)
        self._save_figure(fig, output_path)

    def _plot_series_on_axis(
        self,
        ax: "matplotlib.axes.Axes",
        df: "pd.DataFrame",
        x_col: str,
        y_cols: list[str],
        chart_type: str,
        colors: list[str],
    ) -> None:
        """Plot series on the given axis based on chart type."""
        import numpy as np

        for i, y_col in enumerate(y_cols):
            color = colors[i] if i < len(colors) else colors[0]

            if chart_type == "line":
                ax.plot(df[x_col], df[y_col], label=y_col, color=color)
            elif chart_type == "bar":
                x = np.arange(len(df))
                width = 0.8 / len(y_cols)
                offset = (i - len(y_cols) / 2 + 0.5) * width
                ax.bar(x + offset, df[y_col], width, label=y_col, color=color)
                ax.set_xticks(x)
                ax.set_xticklabels(df[x_col], rotation=45, ha="right")
            elif chart_type == "scatter":
                ax.scatter(df[x_col], df[y_col], label=y_col, color=color, alpha=0.7)
            elif chart_type == "area":
                ax.fill_between(
                    df[x_col], df[y_col], alpha=0.5, label=y_col, color=color
                )
                ax.plot(df[x_col], df[y_col], color=color)
