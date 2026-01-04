"""Overlay implementations for chartbook.plotting."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pandas as pd

from chartbook.plotting._exceptions import FREDAPIError

# Named CSS colors to RGB mapping (common colors)
_NAMED_COLORS = {
    "blue": (0, 0, 255),
    "red": (255, 0, 0),
    "green": (0, 128, 0),
    "orange": (255, 165, 0),
    "purple": (128, 0, 128),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "pink": (255, 192, 203),
    "brown": (165, 42, 42),
    "navy": (0, 0, 128),
    "teal": (0, 128, 128),
    "olive": (128, 128, 0),
    "lime": (0, 255, 0),
    "aqua": (0, 255, 255),
    "maroon": (128, 0, 0),
    "silver": (192, 192, 192),
    "coral": (255, 127, 80),
    "salmon": (250, 128, 114),
    "gold": (255, 215, 0),
    "indigo": (75, 0, 130),
    "violet": (238, 130, 238),
    "steelblue": (70, 130, 180),
}


def _color_to_rgba(color: str, alpha: float) -> str:
    """Convert a color string to rgba format with the given alpha.

    Handles:
    - rgba(...) strings (returns as-is, ignoring alpha parameter)
    - rgb(...) strings (adds alpha)
    - hex colors (#RRGGBB or #RGB)
    - named CSS colors (blue, red, etc.)
    """
    color = color.strip().lower()

    # Already rgba - return as-is
    if color.startswith("rgba("):
        return color

    # rgb(...) - insert alpha
    if color.startswith("rgb("):
        inner = color[4:-1]  # Extract "r, g, b"
        return f"rgba({inner}, {alpha})"

    # Hex color
    if color.startswith("#"):
        hex_color = color[1:]
        if len(hex_color) == 3:
            # Short form #RGB -> #RRGGBB
            hex_color = "".join(c * 2 for c in hex_color)
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return f"rgba({r}, {g}, {b}, {alpha})"

    # Named color
    if color in _NAMED_COLORS:
        r, g, b = _NAMED_COLORS[color]
        return f"rgba({r}, {g}, {b}, {alpha})"

    # Fallback: try using matplotlib's color converter
    try:
        import matplotlib.colors as mcolors

        rgb = mcolors.to_rgb(color)
        r, g, b = int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255)
        return f"rgba({r}, {g}, {b}, {alpha})"
    except (ImportError, ValueError):
        pass

    # Last resort: return a default
    return f"rgba(0, 100, 255, {alpha})"


if TYPE_CHECKING:
    import matplotlib.axes
    import plotly.graph_objects as go

    from chartbook.plotting._types import OverlayConfig


def get_nber_recessions() -> pd.DataFrame:
    """Fetch NBER recession dates from FRED via pandas_datareader.

    Returns DataFrame with columns: start, end

    Raises
    ------
    FREDAPIError
        If pandas_datareader is not installed or API call fails.
    """
    try:
        import pandas_datareader.data as web

        # USREC is the NBER recession indicator (1 = recession, 0 = expansion)
        usrec = web.DataReader(
            "USREC", "fred", "1854-01-01", datetime.now().strftime("%Y-%m-%d")
        )
        usrec = usrec["USREC"]

        # Convert to recession periods (start/end pairs)
        recessions = []
        in_recession = False
        start_date = None

        for date, value in usrec.items():
            if value == 1 and not in_recession:
                start_date = date
                in_recession = True
            elif value == 0 and in_recession:
                recessions.append({"start": start_date, "end": date})
                in_recession = False

        # Handle ongoing recession
        if in_recession:
            recessions.append({"start": start_date, "end": usrec.index[-1]})

        return pd.DataFrame(recessions)

    except ImportError:
        raise FREDAPIError(
            "pandas_datareader package not installed. "
            "Install with: pip install pandas-datareader"
        )
    except Exception as e:
        raise FREDAPIError(str(e))


def filter_recessions_for_range(
    recessions: pd.DataFrame,
    x_min: datetime | pd.Timestamp | None = None,
    x_max: datetime | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Filter recessions to those overlapping with the given date range."""
    if recessions.empty:
        return recessions

    result = recessions.copy()

    if x_min is not None:
        result = result[result["end"] >= x_min]
    if x_max is not None:
        result = result[result["start"] <= x_max]

    return result


def apply_overlays_plotly(
    fig: "go.Figure",
    overlay: "OverlayConfig",
    df: pd.DataFrame,
    x_col: str,
) -> None:
    """Apply all overlays to a Plotly figure."""
    # Determine x-axis range from data
    x_data = df[x_col]
    x_min = x_data.min() if len(x_data) > 0 else None
    x_max = x_data.max() if len(x_data) > 0 else None

    # NBER recession shading
    if overlay.nber_recessions:
        try:
            recessions = get_nber_recessions()
            filtered = filter_recessions_for_range(recessions, x_min, x_max)

            for _, row in filtered.iterrows():
                fig.add_vrect(
                    x0=row["start"],
                    x1=row["end"],
                    fillcolor="rgba(128, 128, 128, 0.2)",
                    layer="below",
                    line_width=0,
                )
        except FREDAPIError:
            # Skip recession shading if API fails
            pass

    # Custom shaded regions
    for region in overlay.shaded_regions:
        fig.add_vrect(
            x0=region["x0"],
            x1=region["x1"],
            fillcolor=region.get("color", "rgba(128, 128, 128, 0.3)"),
            opacity=region.get("alpha", region.get("opacity", 0.3)),
            layer="below",
            line_width=0,
            annotation_text=region.get("label"),
            annotation_position="top left" if region.get("label") else None,
        )

    # Horizontal lines
    for hline in overlay.hlines:
        y_val = hline["y"]
        color = hline.get("color", "gray")
        dash = hline.get("dash", "solid")
        width = hline.get("width", 1)
        label = hline.get("label")

        # Use add_shape + add_trace for legend support
        fig.add_shape(
            type="line",
            x0=0,
            x1=1,
            xref="paper",
            y0=y_val,
            y1=y_val,
            line_color=color,
            line_dash=dash,
            line_width=width,
        )

        # Add invisible trace for legend entry
        if label:
            fig.add_trace(
                dict(
                    type="scatter",
                    x=[None],
                    y=[None],
                    mode="lines",
                    line=dict(color=color, dash=dash, width=width),
                    name=label,
                    showlegend=True,
                )
            )

    # Vertical lines
    for vline in overlay.vlines:
        x_val = vline["x"]
        # Use add_shape + add_annotation instead of add_vline to avoid
        # Plotly's annotation positioning bug with date strings
        fig.add_shape(
            type="line",
            x0=x_val,
            x1=x_val,
            y0=0,
            y1=1,
            yref="paper",
            line_color=vline.get("color", "gray"),
            line_dash=vline.get("dash", "solid"),
            line_width=vline.get("width", 1),
        )
        if vline.get("label"):
            fig.add_annotation(
                x=x_val,
                y=1,
                yref="paper",
                text=vline.get("label"),
                showarrow=False,
                yanchor="bottom",
            )

    # Bands (fill between y columns)
    for band in overlay.bands:
        y_upper_col = band["y_upper"]
        y_lower_col = band["y_lower"]
        color = band.get("color", "blue")
        alpha = band.get("alpha", 0.3)

        # Convert color to rgba
        fill_color = _color_to_rgba(color, alpha)

        # Add upper bound line (invisible, just for fill)
        fig.add_trace(
            dict(
                type="scatter",
                x=df[x_col].tolist(),
                y=df[y_upper_col].tolist(),
                mode="lines",
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
            )
        )

        # Add lower bound with fill to previous trace
        fig.add_trace(
            dict(
                type="scatter",
                x=df[x_col].tolist(),
                y=df[y_lower_col].tolist(),
                mode="lines",
                line=dict(width=0),
                fill="tonexty",
                fillcolor=fill_color,
                showlegend=bool(band.get("label")),
                name=band.get("label", ""),
                hoverinfo="skip",
            )
        )

    # Regression line
    if overlay.regression_line:
        import numpy as np

        # Calculate regression for the first y column
        # (assumes x is numeric or can be converted)
        try:
            x_numeric = pd.to_numeric(df[x_col], errors="coerce")
            if x_numeric.isna().all():
                # Try converting datetime to numeric
                x_numeric = pd.to_datetime(df[x_col]).astype(int) / 10**9
        except Exception:
            x_numeric = np.arange(len(df))

        # Get the y data from the figure's first trace
        if fig.data:
            y_data = fig.data[0].y
            mask = ~(np.isnan(x_numeric) | pd.isna(y_data))
            if mask.sum() > 1:
                coeffs = np.polyfit(x_numeric[mask], np.array(y_data)[mask], 1)
                trend_line = np.polyval(coeffs, x_numeric)

                fig.add_trace(
                    dict(
                        type="scatter",
                        x=df[x_col].tolist(),
                        y=trend_line.tolist(),
                        mode="lines",
                        line=dict(color="red", dash="dash", width=2),
                        name="Trend",
                    )
                )


def apply_overlays_matplotlib(
    ax: "matplotlib.axes.Axes",
    overlay: "OverlayConfig",
    df: pd.DataFrame,
    x_col: str,
) -> None:
    """Apply all overlays to a matplotlib axes."""
    # Determine x-axis range from data
    x_data = df[x_col]
    x_min = x_data.min() if len(x_data) > 0 else None
    x_max = x_data.max() if len(x_data) > 0 else None

    # NBER recession shading
    if overlay.nber_recessions:
        try:
            recessions = get_nber_recessions()
            filtered = filter_recessions_for_range(recessions, x_min, x_max)

            for _, row in filtered.iterrows():
                ax.axvspan(
                    row["start"],
                    row["end"],
                    alpha=0.2,
                    color="gray",
                    zorder=0,
                )
        except FREDAPIError:
            # Skip recession shading if API fails
            pass

    # Custom shaded regions
    for region in overlay.shaded_regions:
        ax.axvspan(
            region["x0"],
            region["x1"],
            alpha=region.get("alpha", region.get("opacity", 0.3)),
            color=region.get("color", "gray"),
            label=region.get("label"),
            zorder=0,
        )

    # Horizontal lines
    for hline in overlay.hlines:
        linestyle_map = {"solid": "-", "dash": "--", "dot": ":", "dashdot": "-."}
        linestyle = linestyle_map.get(hline.get("dash", "solid"), "-")

        ax.axhline(
            y=hline["y"],
            color=hline.get("color", "gray"),
            linestyle=linestyle,
            linewidth=hline.get("width", 1),
            label=hline.get("label"),
            zorder=1,
        )

    # Vertical lines
    for vline in overlay.vlines:
        linestyle_map = {"solid": "-", "dash": "--", "dot": ":", "dashdot": "-."}
        linestyle = linestyle_map.get(vline.get("dash", "solid"), "-")

        ax.axvline(
            x=vline["x"],
            color=vline.get("color", "gray"),
            linestyle=linestyle,
            linewidth=vline.get("width", 1),
            label=vline.get("label"),
            zorder=1,
        )

    # Bands (fill between y columns)
    for band in overlay.bands:
        y_upper_col = band["y_upper"]
        y_lower_col = band["y_lower"]

        ax.fill_between(
            df[x_col],
            df[y_lower_col],
            df[y_upper_col],
            alpha=band.get("alpha", 0.3),
            color=band.get("color", "blue"),
            label=band.get("label"),
            zorder=0,
        )

    # Regression line
    if overlay.regression_line:
        import numpy as np

        # Get the plotted data from the axes
        lines = ax.get_lines()
        if lines:
            x_line = lines[0].get_xdata()
            y_line = lines[0].get_ydata()

            # Convert to numeric if needed
            try:
                x_numeric = pd.to_numeric(x_line, errors="coerce")
                if pd.isna(x_numeric).all():
                    x_numeric = np.arange(len(x_line))
            except Exception:
                x_numeric = np.arange(len(x_line))

            mask = ~(np.isnan(x_numeric) | np.isnan(y_line))
            if mask.sum() > 1:
                coeffs = np.polyfit(x_numeric[mask], y_line[mask], 1)
                trend_line = np.polyval(coeffs, x_numeric)

                ax.plot(
                    x_line,
                    trend_line,
                    color="red",
                    linestyle="--",
                    linewidth=2,
                    label="Trend",
                    zorder=2,
                )
