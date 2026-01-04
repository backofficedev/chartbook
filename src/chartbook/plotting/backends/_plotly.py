"""Plotly backend for interactive chart output."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from chartbook.plotting._config import get_config
from chartbook.plotting.backends._base import BaseBackend

if TYPE_CHECKING:
    import pandas as pd
    import plotly.graph_objects as go

    from chartbook.plotting._types import ChartConfig, DualAxisConfig, OverlayConfig


class PlotlyBackend(BaseBackend):
    """Plotly backend for creating interactive HTML charts."""

    @property
    def name(self) -> str:
        return "plotly"

    def _get_colors(self, config: "ChartConfig", n_series: int) -> list[str]:
        """Get colors for the chart series."""
        if config.color:
            if isinstance(config.color, str):
                return [config.color] * n_series
            return list(config.color)[:n_series]
        return get_config().color_palette[:n_series]

    def _apply_layout(self, fig: "go.Figure", config: "ChartConfig") -> None:
        """Apply common layout configuration."""
        layout_kwargs: dict = {
            "template": get_config().plotly_template,
            "hovermode": "x unified",
        }

        if config.title:
            layout_kwargs["title"] = config.title
        if config.x_title:
            layout_kwargs["xaxis_title"] = config.x_title
        if config.y_title:
            layout_kwargs["yaxis_title"] = config.y_title
        if config.x_range:
            layout_kwargs["xaxis_range"] = list(config.x_range)
        if config.y_range:
            layout_kwargs["yaxis_range"] = list(config.y_range)
        if config.x_tickformat:
            layout_kwargs["xaxis_tickformat"] = config.x_tickformat
        if config.y_tickformat:
            layout_kwargs["yaxis_tickformat"] = config.y_tickformat

        fig.update_layout(**layout_kwargs)

    def _add_annotations(self, fig: "go.Figure", config: "ChartConfig") -> None:
        """Add caption, note, and source as annotations."""
        annotations = []
        y_offset = -0.12

        if config.caption:
            annotations.append(
                dict(
                    text=config.caption,
                    xref="paper",
                    yref="paper",
                    x=0.5,
                    y=y_offset,
                    showarrow=False,
                    font=dict(size=11),
                    xanchor="center",
                )
            )
            y_offset -= 0.05

        if config.note:
            annotations.append(
                dict(
                    text=f"<i>Note: {config.note}</i>",
                    xref="paper",
                    yref="paper",
                    x=0,
                    y=y_offset,
                    showarrow=False,
                    font=dict(size=9),
                    xanchor="left",
                )
            )
            y_offset -= 0.04

        if config.source:
            annotations.append(
                dict(
                    text=f"Source: {config.source}",
                    xref="paper",
                    yref="paper",
                    x=0,
                    y=y_offset,
                    showarrow=False,
                    font=dict(size=9),
                    xanchor="left",
                )
            )

        if annotations:
            fig.update_layout(
                annotations=annotations,
                margin=dict(b=100),  # Extra bottom margin for annotations
            )

    def _apply_overlays(
        self, fig: "go.Figure", overlay: "OverlayConfig", df: "pd.DataFrame", x_col: str
    ) -> None:
        """Apply overlays to the figure."""
        from chartbook.plotting._overlays import apply_overlays_plotly

        apply_overlays_plotly(fig, overlay, df, x_col)

    def _save_figure(
        self, fig: "go.Figure", output_path: Path, size: tuple[float, float]
    ) -> None:
        """Save figure to HTML file.

        Note: Interactive HTML files are saved without explicit dimensions
        to enable responsive behavior in the browser.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(str(output_path), include_plotlyjs="cdn")

    def build_line(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        size: tuple[float, float],
    ) -> "go.Figure":
        """Build a line chart figure without saving."""
        import plotly.graph_objects as go

        fig = go.Figure()
        colors = self._get_colors(config, len(config.y))

        for i, y_col in enumerate(config.y):
            label = config.labels.get(y_col, y_col) if config.labels else y_col
            fig.add_trace(
                go.Scatter(
                    x=df[config.x],
                    y=df[y_col],
                    mode="lines",
                    name=label,
                    line=dict(color=colors[i]),
                )
            )

        self._apply_layout(fig, config)
        self._apply_overlays(fig, overlay, df, config.x)
        self._add_annotations(fig, config)

        return fig

    def create_line(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a line chart and save to file."""
        fig = self.build_line(df, config, overlay, size)
        self._save_figure(fig, output_path, size)

    def build_bar(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        size: tuple[float, float],
    ) -> "go.Figure":
        """Build a bar chart figure without saving."""
        import plotly.graph_objects as go

        fig = go.Figure()
        colors = self._get_colors(config, len(config.y))

        for i, y_col in enumerate(config.y):
            label = config.labels.get(y_col, y_col) if config.labels else y_col
            fig.add_trace(
                go.Bar(
                    x=df[config.x],
                    y=df[y_col],
                    name=label,
                    marker_color=colors[i],
                )
            )

        barmode = "stack" if config.stacked else "group"
        fig.update_layout(barmode=barmode)

        self._apply_layout(fig, config)
        self._apply_overlays(fig, overlay, df, config.x)
        self._add_annotations(fig, config)

        return fig

    def create_bar(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a bar chart and save to file."""
        fig = self.build_bar(df, config, overlay, size)
        self._save_figure(fig, output_path, size)

    def build_scatter(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        size: tuple[float, float],
    ) -> "go.Figure":
        """Build a scatter chart figure without saving."""
        import plotly.graph_objects as go

        fig = go.Figure()
        y_col = config.y[0]  # Scatter uses first y column

        # Handle size mapping
        sizes = None
        if config.size and config.size in df.columns:
            sizes = df[config.size]
            # Normalize to reasonable marker sizes
            sizes = (sizes - sizes.min()) / (sizes.max() - sizes.min()) * 30 + 5

        # Handle color by category
        if config.color_by and config.color_by in df.columns:
            categories = df[config.color_by].unique()
            colors = get_config().color_palette[: len(categories)]

            for cat, color in zip(categories, colors):
                mask = df[config.color_by] == cat
                cat_sizes = sizes[mask] if sizes is not None else None
                fig.add_trace(
                    go.Scatter(
                        x=df.loc[mask, config.x],
                        y=df.loc[mask, y_col],
                        mode="markers",
                        name=str(cat),
                        marker=dict(color=color, size=cat_sizes, opacity=0.7),
                    )
                )
        else:
            color = self._get_colors(config, 1)[0]
            fig.add_trace(
                go.Scatter(
                    x=df[config.x],
                    y=df[y_col],
                    mode="markers",
                    marker=dict(color=color, size=sizes, opacity=0.7),
                )
            )

        self._apply_layout(fig, config)
        self._apply_overlays(fig, overlay, df, config.x)
        self._add_annotations(fig, config)

        return fig

    def create_scatter(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a scatter chart and save to file."""
        fig = self.build_scatter(df, config, overlay, size)
        self._save_figure(fig, output_path, size)

    def build_pie(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        size: tuple[float, float],
    ) -> "go.Figure":
        """Build a pie chart figure without saving."""
        import plotly.graph_objects as go

        names_col = config.names or config.x
        values_col = config.values or config.y[0]

        colors = get_config().color_palette[: len(df)]

        fig = go.Figure(
            data=[
                go.Pie(
                    labels=df[names_col],
                    values=df[values_col],
                    marker=dict(colors=colors),
                    textinfo="percent+label",
                )
            ]
        )

        self._apply_layout(fig, config)
        self._add_annotations(fig, config)

        return fig

    def create_pie(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a pie chart and save to file."""
        fig = self.build_pie(df, config, overlay, size)
        self._save_figure(fig, output_path, size)

    def build_area(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        size: tuple[float, float],
    ) -> "go.Figure":
        """Build an area chart figure without saving."""
        import plotly.graph_objects as go

        fig = go.Figure()
        colors = self._get_colors(config, len(config.y))

        stackgroup = "one" if config.stacked else None

        for i, y_col in enumerate(config.y):
            label = config.labels.get(y_col, y_col) if config.labels else y_col
            fig.add_trace(
                go.Scatter(
                    x=df[config.x],
                    y=df[y_col],
                    mode="lines",
                    name=label,
                    fill="tonexty" if config.stacked else "tozeroy",
                    stackgroup=stackgroup,
                    line=dict(color=colors[i]),
                    fillcolor=colors[i].replace(")", ", 0.5)").replace("rgb", "rgba")
                    if colors[i].startswith("rgb")
                    else colors[i],
                )
            )

        self._apply_layout(fig, config)
        self._apply_overlays(fig, overlay, df, config.x)
        self._add_annotations(fig, config)

        return fig

    def create_area(
        self,
        df: "pd.DataFrame",
        config: "ChartConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create an area chart and save to file."""
        fig = self.build_area(df, config, overlay, size)
        self._save_figure(fig, output_path, size)

    def build_dual_axis(
        self,
        df: "pd.DataFrame",
        config: "DualAxisConfig",
        overlay: "OverlayConfig",
        size: tuple[float, float],
    ) -> "go.Figure":
        """Build a dual-axis chart figure without saving."""
        from plotly.subplots import make_subplots

        fig = make_subplots(specs=[[{"secondary_y": True}]])

        left_colors = (
            config.left_colors or get_config().color_palette[: len(config.left_y)]
        )
        right_colors = (
            config.right_colors
            or get_config().color_palette[
                len(config.left_y) : len(config.left_y) + len(config.right_y)
            ]
        )

        # Add left axis traces
        for i, y_col in enumerate(config.left_y):
            color = left_colors[i] if i < len(left_colors) else left_colors[0]
            trace = self._create_trace_for_type(
                df, config.x, y_col, config.left_type, color
            )
            fig.add_trace(trace, secondary_y=False)

        # Add right axis traces
        for i, y_col in enumerate(config.right_y):
            color = right_colors[i] if i < len(right_colors) else right_colors[0]
            trace = self._create_trace_for_type(
                df, config.x, y_col, config.right_type, color
            )
            fig.add_trace(trace, secondary_y=True)

        # Update layout
        layout_kwargs: dict = {
            "template": get_config().plotly_template,
            "hovermode": "x unified",
        }

        if config.title:
            layout_kwargs["title"] = config.title
        if config.x_title:
            layout_kwargs["xaxis_title"] = config.x_title

        fig.update_layout(**layout_kwargs)

        if config.left_y_title:
            fig.update_yaxes(title_text=config.left_y_title, secondary_y=False)
        if config.right_y_title:
            fig.update_yaxes(title_text=config.right_y_title, secondary_y=True)
        if config.left_y_range:
            fig.update_yaxes(range=list(config.left_y_range), secondary_y=False)
        if config.right_y_range:
            fig.update_yaxes(range=list(config.right_y_range), secondary_y=True)
        if config.left_y_tickformat:
            fig.update_yaxes(tickformat=config.left_y_tickformat, secondary_y=False)
        if config.right_y_tickformat:
            fig.update_yaxes(tickformat=config.right_y_tickformat, secondary_y=True)

        # Apply overlays
        from chartbook.plotting._overlays import apply_overlays_plotly

        apply_overlays_plotly(fig, overlay, df, config.x)

        return fig

    def create_dual_axis(
        self,
        df: "pd.DataFrame",
        config: "DualAxisConfig",
        overlay: "OverlayConfig",
        output_path: Path,
        size: tuple[float, float],
    ) -> None:
        """Create a dual-axis chart and save to file."""
        fig = self.build_dual_axis(df, config, overlay, size)
        self._save_figure(fig, output_path, size)

    def _create_trace_for_type(
        self,
        df: "pd.DataFrame",
        x_col: str,
        y_col: str,
        chart_type: str,
        color: str,
    ):
        """Create a plotly trace based on chart type."""
        import plotly.graph_objects as go

        if chart_type == "line":
            return go.Scatter(
                x=df[x_col],
                y=df[y_col],
                mode="lines",
                name=y_col,
                line=dict(color=color),
            )
        elif chart_type == "bar":
            return go.Bar(
                x=df[x_col],
                y=df[y_col],
                name=y_col,
                marker_color=color,
            )
        elif chart_type == "scatter":
            return go.Scatter(
                x=df[x_col],
                y=df[y_col],
                mode="markers",
                name=y_col,
                marker=dict(color=color),
            )
        elif chart_type == "area":
            return go.Scatter(
                x=df[x_col],
                y=df[y_col],
                mode="lines",
                name=y_col,
                fill="tozeroy",
                line=dict(color=color),
            )
        else:
            raise ValueError(f"Unknown chart type: {chart_type}")
