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

    @staticmethod
    def _apply_tickformat(axis, fmt: str | None) -> None:
        """Apply a Plotly/d3-style numeric or strftime tick format to a Matplotlib axis."""
        if not fmt:
            return
        import matplotlib.dates as mdates
        import matplotlib.ticker as mticker

        # strftime date formats (e.g. "%Y-%m", "%b %Y") start with "%" or contain "%Y"/"%m"/"%d"
        if any(tok in fmt for tok in ("%Y", "%y", "%m", "%b", "%B", "%d", "%H", "%M", "%S")):
            axis.set_major_formatter(mdates.DateFormatter(fmt))
            return
        # Numeric format spec (e.g. ".1%", ",.0f", "$,.2f")
        prefix = ""
        spec = fmt
        if spec.startswith("$"):
            prefix = "$"
            spec = spec[1:]
        try:
            format(1.0, spec)
        except (ValueError, TypeError):
            return

        def _fmt(val, _pos, _prefix=prefix, _spec=spec):
            try:
                return f"{_prefix}{format(val, _spec)}"
            except (ValueError, TypeError):
                return str(val)

        axis.set_major_formatter(mticker.FuncFormatter(_fmt))

    def _apply_config(
        self,
        ax: "matplotlib.axes.Axes",
        config: "ChartConfig",
        x_series: "pd.Series | None" = None,
        use_positional_x: bool = False,
    ) -> None:
        """Apply chart configuration to axes."""
        if config.title:
            ax.set_title(config.title)
        if config.x_title:
            ax.set_xlabel(config.x_title)
        if config.y_title:
            ax.set_ylabel(config.y_title)
        if config.x_range:
            if x_series is not None:
                from chartbook.plotting._overlays import _mpl_x_coord

                ax.set_xlim(
                    (
                        _mpl_x_coord(config.x_range[0], x_series, use_positional_x),
                        _mpl_x_coord(config.x_range[1], x_series, use_positional_x),
                    )
                )
            else:
                ax.set_xlim(config.x_range)
        if config.y_range:
            ax.set_ylim(config.y_range)
        if config.x_tickformat:
            self._apply_tickformat(ax.xaxis, config.x_tickformat)
        if config.y_tickformat:
            self._apply_tickformat(ax.yaxis, config.y_tickformat)

    def _apply_overlays(
        self,
        ax: "matplotlib.axes.Axes",
        overlay: "OverlayConfig",
        df: "pd.DataFrame",
        x_col: str,
        *,
        use_positional_x: bool = False,
    ) -> None:
        """Apply overlays to the axes."""
        from chartbook.plotting._overlays import apply_overlays_matplotlib

        apply_overlays_matplotlib(ax, overlay, df, x_col, use_positional_x=use_positional_x)

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
            from matplotlib.transforms import offset_copy

            annotation_text = "\n".join(annotations)
            # Below all that is under the axes, the tick labels and the x-axis
            # title, wherever their size put them: a fixed place overlapped the title
            fig.canvas.draw()
            under = ax.get_tightbbox(fig.canvas.get_renderer())
            top = ax.transAxes.inverted().transform((0, under.y0))[1]
            fig.text(
                0.5,
                top,
                annotation_text,
                ha="center",
                va="top",
                fontsize=9,
                transform=offset_copy(ax.transAxes, fig=fig, y=-6, units="points"),
                wrap=True,
            )

    def _save_figure(self, fig: "matplotlib.figure.Figure", output_path: Path) -> None:
        """Save figure to file."""
        import matplotlib.pyplot as plt

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(output_path, bbox_inches="tight", dpi=300)
        finally:
            plt.close(fig)

    def _get_colors(self, config: "ChartConfig", n_series: int) -> list[str]:
        """Get colors for the chart series."""
        if config.color:
            if isinstance(config.color, str):
                return [config.color] * n_series
            palette = list(config.color)
            if palette:
                return [palette[i % len(palette)] for i in range(n_series)]
        palette = get_config().color_palette
        return [palette[i % len(palette)] for i in range(n_series)]

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

        pre_labels = len(ax.get_legend_handles_labels()[1])
        self._apply_config(ax, config, x_series=df[config.x])
        self._apply_overlays(ax, overlay, df, config.x)
        if len(config.y) > 1 or len(ax.get_legend_handles_labels()[1]) > pre_labels:
            ax.legend()
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

        import pandas as pd

        pos_bottom = np.zeros(len(df)) if config.stacked else None
        neg_bottom = np.zeros(len(df)) if config.stacked else None

        for i, y_col in enumerate(config.y):
            label = config.labels.get(y_col, y_col) if config.labels else y_col
            vals = pd.to_numeric(df[y_col], errors="coerce").to_numpy(dtype=float)

            if config.stacked:
                stacked_vals = np.nan_to_num(vals, nan=0.0)
                bottoms = np.where(stacked_vals >= 0, pos_bottom, neg_bottom)
                ax.bar(x, stacked_vals, width, label=label, color=colors[i], bottom=bottoms)
                pos_bottom = pos_bottom + np.maximum(stacked_vals, 0.0)
                neg_bottom = neg_bottom + np.minimum(stacked_vals, 0.0)
            else:
                offset = (i - len(config.y) / 2 + 0.5) * width
                ax.bar(x + offset, vals, width, label=label, color=colors[i])

        # Set x-tick labels
        ax.set_xticks(x)
        ax.set_xticklabels(df[config.x], rotation=45, ha="right")

        pre_labels = len(ax.get_legend_handles_labels()[1])
        self._apply_config(ax, config, x_series=df[config.x], use_positional_x=True)
        self._apply_overlays(ax, overlay, df, config.x, use_positional_x=True)
        if len(config.y) > 1 or len(ax.get_legend_handles_labels()[1]) > pre_labels:
            ax.legend()
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
            import pandas as pd

            sizes = pd.to_numeric(df[config.size], errors="coerce").astype(float)
            # Normalize sizes to reasonable marker sizes
            span = sizes.max() - sizes.min()
            if pd.isna(span) or span == 0:
                sizes = pd.Series(60.0, index=df.index)
            else:
                sizes = ((sizes - sizes.min()) / span * 200 + 20).fillna(60.0)

        # Handle color by category
        if config.color_by and config.color_by in df.columns:
            import pandas as pd

            categories = df[config.color_by].unique()
            palette = get_config().color_palette
            colors = [palette[i % len(palette)] for i in range(len(categories))]
            for cat, color in zip(categories, colors):
                mask = (
                    df[config.color_by].isna()
                    if pd.isna(cat)
                    else (df[config.color_by] == cat).fillna(False)
                )
                cat_sizes = sizes[mask] if sizes is not None else None
                ax.scatter(
                    df.loc[mask, config.x],
                    df.loc[mask, y_col],
                    s=cat_sizes,
                    c=color,
                    label=str(cat),
                    alpha=0.7,
                )
            has_category_legend = True
        else:
            color = self._get_colors(config, 1)[0]
            ax.scatter(df[config.x], df[y_col], s=sizes, c=color, alpha=0.7)
            has_category_legend = False

        pre_labels = len(ax.get_legend_handles_labels()[1])
        self._apply_config(ax, config, x_series=df[config.x])
        self._apply_overlays(ax, overlay, df, config.x)
        if has_category_legend or len(ax.get_legend_handles_labels()[1]) > pre_labels:
            ax.legend()
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

        import numpy as np
        import pandas as pd

        numeric_vals = pd.to_numeric(df[values_col], errors="coerce")
        valid = numeric_vals.notna() & np.isfinite(numeric_vals) & (numeric_vals >= 0)
        valid_vals = numeric_vals[valid]
        valid_df = df.loc[valid]
        if not valid_vals.empty and valid_vals.sum() != 0:
            colors = get_config().color_palette[: len(valid_df)]
            wedges, texts, autotexts = ax.pie(
                valid_vals,
                labels=valid_df[names_col],
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

        pre_labels = len(ax.get_legend_handles_labels()[1])
        self._apply_config(ax, config, x_series=df[config.x])
        self._apply_overlays(ax, overlay, df, config.x)
        if len(config.y) > 1 or len(ax.get_legend_handles_labels()[1]) > pre_labels:
            ax.legend()
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

        palette = get_config().color_palette
        left_colors = (
            config.left_colors
            or [palette[i % len(palette)] for i in range(len(config.left_y))]
        )
        right_colors = (
            config.right_colors
            or [palette[(len(config.left_y) + i) % len(palette)] for i in range(len(config.right_y))]
        )

        # If either axis uses bars, both axes share integer positional x coordinates
        # so datetime/categorical x-axes don't mismatch epoch days vs 0..N-1.
        use_positional_x = config.left_type == "bar" or config.right_type == "bar"
        both_bars = config.left_type == "bar" and config.right_type == "bar"
        total_bars = len(config.left_y) + len(config.right_y) if both_bars else None

        # Plot left axis
        self._plot_series_on_axis(
            ax1, df, config.x, config.left_y, config.left_type, left_colors,
            use_positional_x=use_positional_x,
            bar_slot_offset=0,
            bar_total_slots=total_bars,
        )

        # Plot right axis
        self._plot_series_on_axis(
            ax2, df, config.x, config.right_y, config.right_type, right_colors,
            use_positional_x=use_positional_x,
            bar_slot_offset=len(config.left_y) if both_bars else 0,
            bar_total_slots=total_bars,
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
        if config.left_y_tickformat:
            self._apply_tickformat(ax1.yaxis, config.left_y_tickformat)
        if config.right_y_tickformat:
            self._apply_tickformat(ax2.yaxis, config.right_y_tickformat)

        # Apply overlays to left axis before collecting legend entries
        from chartbook.plotting._overlays import apply_overlays_matplotlib

        apply_overlays_matplotlib(ax1, overlay, df, config.x, use_positional_x=use_positional_x)

        # Combine legends
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        if labels1 or labels2:
            ax1.legend(lines1 + lines2, labels1 + labels2, loc="best")
        # Its caption, note and source, which were not drawn
        self._add_annotations(fig, ax1, config)

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
        *,
        use_positional_x: bool = False,
        bar_slot_offset: int = 0,
        bar_total_slots: int | None = None,
    ) -> None:
        """Plot series on the given axis based on chart type."""
        import numpy as np
        import pandas as pd

        x_vals = np.arange(len(df)) if use_positional_x else df[x_col]

        for i, y_col in enumerate(y_cols):
            color = colors[i] if i < len(colors) else colors[0]

            if chart_type == "line":
                ax.plot(x_vals, df[y_col], label=y_col, color=color)
            elif chart_type == "bar":
                x = np.arange(len(df))
                total = bar_total_slots if bar_total_slots is not None else len(y_cols)
                width = 0.8 / total
                slot = bar_slot_offset + i
                offset = (slot - total / 2 + 0.5) * width
                vals = pd.to_numeric(df[y_col], errors="coerce").to_numpy(dtype=float)
                ax.bar(x + offset, vals, width, label=y_col, color=color)
                ax.set_xticks(x)
                ax.set_xticklabels(df[x_col], rotation=45, ha="right")
            elif chart_type == "scatter":
                ax.scatter(x_vals, df[y_col], label=y_col, color=color, alpha=0.7)
            elif chart_type == "area":
                vals = pd.to_numeric(df[y_col], errors="coerce").to_numpy(dtype=float)
                ax.fill_between(
                    x_vals, vals, alpha=0.5, label=y_col, color=color
                )
                ax.plot(x_vals, vals, color=color)
