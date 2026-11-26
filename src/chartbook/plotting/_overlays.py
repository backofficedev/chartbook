"""Overlay implementations for chartbook.plotting."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from chartbook.plotting._exceptions import FREDAPIError


def _datetime_series_to_seconds(dt: pd.Series) -> np.ndarray:
    """Convert a parsed datetime Series to float epoch seconds, preserving NaT as NaN across all pandas units."""
    if getattr(dt.dt, "tz", None) is not None:
        dt = dt.dt.tz_convert("UTC").dt.tz_localize(None)
    return (dt - pd.Timestamp("1970-01-01")).dt.total_seconds().to_numpy(dtype=float)


def _x_values_to_numeric(x_values) -> np.ndarray:
    """Convert x values (numeric, datetime, date, or date strings) to float array, preserving NaT/None as NaN."""
    x_series = pd.Series(x_values)
    non_null = x_series.dropna()
    is_dt = pd.api.types.is_datetime64_any_dtype(x_series) or (
        not non_null.empty
        and any(isinstance(v, (pd.Timestamp, date, datetime, np.datetime64)) for v in non_null)
    )
    if is_dt:
        dt = pd.to_datetime(x_series, errors="coerce", utc=True)
        return _datetime_series_to_seconds(dt)
    try:
        x_numeric = pd.to_numeric(x_series, errors="coerce")
        if x_numeric.isna().all():
            dt = pd.to_datetime(x_series, errors="coerce", utc=True)
            if not dt.isna().all():
                return _datetime_series_to_seconds(dt)
            return np.arange(len(x_series), dtype=float)
        return x_numeric.to_numpy(dtype=float)
    except Exception:
        return np.arange(len(x_series), dtype=float)

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


def _as_naive_utc(value: Any) -> pd.Timestamp | None:
    """Convert a datetime-like bound to a tz-naive UTC Timestamp, or None if not datetime-like."""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (datetime, pd.Timestamp, np.datetime64)):
        ts = pd.Timestamp(value)
        if ts.tzinfo is not None:
            return ts.tz_convert("UTC").tz_localize(None)
        return ts
    if isinstance(value, date):
        return pd.Timestamp(value)
    if isinstance(value, str):
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            return None
        if ts.tzinfo is not None:
            return ts.tz_convert("UTC").tz_localize(None)
        return ts
    return None


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
        bound_min = _as_naive_utc(x_min)
        if bound_min is None:
            return result.iloc[0:0]
        result = result[result["end"] >= bound_min]
    if x_max is not None:
        bound_max = _as_naive_utc(x_max)
        if bound_max is None:
            return result.iloc[0:0]
        result = result[result["start"] <= bound_max]

    return result


def _x_range(x_data: pd.Series) -> tuple:
    """The least and greatest x, which the recession shading is cut to; None for each when there is no order.

    Worked out only for the shading, so that a chart with none never asks:
    an x column of an unordered pandas category has no least or greatest.
    """
    if len(x_data) == 0:
        return None, None
    if isinstance(x_data.dtype, pd.CategoricalDtype) and not x_data.cat.ordered:
        return None, None
    non_null = x_data.dropna()
    if non_null.empty:
        return None, None
    try:
        return non_null.min(), non_null.max()
    except TypeError:
        return None, None


def apply_overlays_plotly(
    fig: "go.Figure",
    overlay: "OverlayConfig",
    df: pd.DataFrame,
    x_col: str,
) -> None:
    """Apply all overlays to a Plotly figure."""
    # NBER recession shading
    if overlay.nber_recessions:
        try:
            x_min, x_max = _x_range(df[x_col])
            if x_min is not None or x_max is not None:
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

        if fig.data:
            if len(fig.data) > 1 and len(fig.data[0].y) != len(df):
                marker_traces = [t for t in fig.data if getattr(t, "mode", None) == "markers"]
                traces = marker_traces or list(fig.data)
                x_raw = [v for t in traces for v in (t.x if t.x is not None else [])]
                y_raw = [v for t in traces for v in (t.y if t.y is not None else [])]
            else:
                x_raw = list(fig.data[0].x) if fig.data[0].x is not None else df[x_col].tolist()
                y_raw = list(fig.data[0].y) if fig.data[0].y is not None else []

            if len(x_raw) == len(y_raw) and len(x_raw) > 1:
                x_arr = _x_values_to_numeric(x_raw)
                y_arr = pd.to_numeric(pd.Series(y_raw), errors="coerce").to_numpy(dtype=float)
                mask = np.isfinite(x_arr) & np.isfinite(y_arr)
                if mask.sum() > 1:
                    coeffs = np.polyfit(x_arr[mask], y_arr[mask], 1)
                    order = np.argsort(x_arr[mask])
                    x_valid = [x_raw[i] for i in np.flatnonzero(mask)[order]]
                    trend_line = np.polyval(coeffs, x_arr[mask][order])

                    fig.add_trace(
                        dict(
                            type="scatter",
                            x=x_valid,
                            y=trend_line.tolist(),
                            mode="lines",
                            line=dict(color="red", dash="dash", width=2),
                            name="Trend",
                        )
                    )


def _mpl_x_coord(val: Any, x_series: pd.Series, use_positional_x: bool = False) -> Any:
    """Coerce an overlay x coordinate (e.g. date string or Timestamp) for Matplotlib."""
    is_dt64 = pd.api.types.is_datetime64_any_dtype(x_series)
    non_null = x_series.dropna()
    is_dt = is_dt64 or (
        not non_null.empty
        and any(isinstance(v, (pd.Timestamp, date, datetime, np.datetime64)) for v in non_null)
    )
    if is_dt and isinstance(val, str):
        val = pd.to_datetime(val)
    if use_positional_x:
        if len(x_series) == 0:
            return val
        if is_dt or pd.api.types.is_numeric_dtype(x_series):
            x_num = _x_values_to_numeric(x_series)
            v_num = _x_values_to_numeric(pd.Series([val]))[0]
            finite = np.isfinite(x_num)
            if np.isfinite(v_num) and finite.any():
                idx = np.flatnonzero(finite)
                order = idx[np.argsort(x_num[idx])]
                return float(np.interp(v_num, x_num[order], order))
        matches = np.where(x_series.astype(str).to_numpy() == str(val))[0]
        if len(matches) > 0:
            return float(matches[0])
        return val
    if is_dt and isinstance(val, (datetime, pd.Timestamp, np.datetime64)):
        ts = pd.Timestamp(val)
        tz = getattr(x_series.dt, "tz", None) if is_dt64 else None
        if tz is not None and ts.tzinfo is None:
            return ts.tz_localize("UTC").tz_convert(tz)
        if tz is None and ts.tzinfo is not None:
            return ts.tz_convert("UTC").tz_localize(None)
        return ts
    return val


def apply_overlays_matplotlib(
    ax: "matplotlib.axes.Axes",
    overlay: "OverlayConfig",
    df: pd.DataFrame,
    x_col: str,
    *,
    use_positional_x: bool = False,
) -> None:
    """Apply all overlays to a matplotlib axes."""
    # Capture plotted data artists before overlays (hlines/vlines) add lines
    data_lines = list(ax.get_lines())
    data_collections = list(ax.collections)

    # NBER recession shading
    if overlay.nber_recessions:
        try:
            x_min, x_max = _x_range(df[x_col])
            if x_min is not None or x_max is not None:
                recessions = get_nber_recessions()
                filtered = filter_recessions_for_range(recessions, x_min, x_max)

                for _, row in filtered.iterrows():
                    ax.axvspan(
                        _mpl_x_coord(row["start"], df[x_col], use_positional_x),
                        _mpl_x_coord(row["end"], df[x_col], use_positional_x),
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
            _mpl_x_coord(region["x0"], df[x_col], use_positional_x),
            _mpl_x_coord(region["x1"], df[x_col], use_positional_x),
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
            x=_mpl_x_coord(vline["x"], df[x_col], use_positional_x),
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

        x_line = None
        y_line = None
        if data_lines:
            x_line = np.asarray(data_lines[0].get_xdata())
            y_line = pd.to_numeric(pd.Series(data_lines[0].get_ydata()), errors="coerce").to_numpy(dtype=float)
        elif data_collections:
            offsets = [
                np.asarray(col.get_offsets(), dtype=float)
                for col in data_collections
                if len(col.get_offsets()) > 0
            ]
            if offsets:
                pts = np.vstack(offsets)
                x_line = pts[:, 0]
                y_line = pts[:, 1]

        if x_line is not None and y_line is not None and len(x_line) == len(y_line) and len(x_line) > 1:
            x_numeric = _x_values_to_numeric(x_line)

            mask = np.isfinite(x_numeric) & np.isfinite(y_line)
            if mask.sum() > 1:
                coeffs = np.polyfit(x_numeric[mask], y_line[mask], 1)
                order = np.argsort(x_numeric[mask])
                x_plot = x_line[mask][order]
                trend_line = np.polyval(coeffs, x_numeric[mask][order])

                ax.plot(
                    x_plot,
                    trend_line,
                    color="red",
                    linestyle="--",
                    linewidth=2,
                    label="Trend",
                    zorder=2,
                )
