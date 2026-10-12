"""A ChartBook plotting backend that writes Vega-Lite specifications.

This is the worked example from the "Writing a Plotting Backend" guide: a
complete backend in one file, using nothing outside the standard library.
Each chart is written as a Vega-Lite JSON specification, which is the format
Altair produces and which any Vega-Lite renderer can draw.
"""

import json
from pathlib import Path

from chartbook.plotting.backends import BaseBackend

SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"
PIXELS_PER_INCH = 96


class VegaLiteBackend(BaseBackend):
    """Write each chart as a Vega-Lite JSON specification."""

    @property
    def name(self):
        return "vegalite"

    # The five methods every backend must provide. Each receives the data, the
    # chart's configuration, its overlays, where to write, and a figure size.

    def create_line(self, df, config, overlay, output_path, size):
        self._write(self._xy_spec("line", df, config), config, output_path, size)

    def create_bar(self, df, config, overlay, output_path, size):
        self._write(self._xy_spec("bar", df, config), config, output_path, size)

    def create_scatter(self, df, config, overlay, output_path, size):
        self._write(self._xy_spec("point", df, config), config, output_path, size)

    def create_area(self, df, config, overlay, output_path, size):
        self._write(self._xy_spec("area", df, config), config, output_path, size)

    def create_pie(self, df, config, overlay, output_path, size):
        # A pie is described by config.names and config.values, not x and y
        spec = {
            "mark": "arc",
            "data": {"values": _records(df)},
            "encoding": {
                "theta": {"field": config.values, "type": "quantitative"},
                "color": {"field": config.names, "type": "nominal"},
            },
        }
        self._write(spec, config, output_path, size)

    # create_dual_axis is optional. BaseBackend's version raises
    # NotImplementedError, which is the right answer for a backend without one.

    def _xy_spec(self, mark, df, config):
        return {
            "mark": mark,
            "data": {"values": _records(df)},
            # config.y is always a list. Fold it into one row per
            # (x, series, value) so each y column becomes its own colour.
            "transform": [{"fold": config.y, "as": ["series", "value"]}],
            "encoding": {
                "x": {"field": config.x, "title": config.x_title or config.x},
                "y": {
                    "field": "value",
                    "type": "quantitative",
                    "title": config.y_title,
                },
                "color": {"field": "series", "type": "nominal"},
            },
        }

    def _write(self, spec, config, output_path, size):
        width, height = size  # inches
        spec = {
            "$schema": SCHEMA,
            "title": config.title,
            "width": int(width * PIXELS_PER_INCH),
            "height": int(height * PIXELS_PER_INCH),
            **spec,
        }
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(spec, indent=2))


def _records(df):
    """The dataframe as JSON-ready records, with dates in ISO format."""
    return json.loads(df.to_json(orient="records", date_format="iso"))


#: What the entry point names: an instance, not the class.
backend = VegaLiteBackend()
