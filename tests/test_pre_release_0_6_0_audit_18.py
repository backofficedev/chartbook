"""Regression tests for the eighteenth pre-release 0.6.0 audit."""

from __future__ import annotations

import pandas as pd

from chartbook import plotting


class TestAudit18PlottingOverlaysAndCoercion:
    def test_matplotlib_regression_line_without_bands_does_not_raise_unbound_local(self, tmp_path):
        df = pd.DataFrame({"x": [1, 2, 3, 4], "y": [1.0, 2.0, 3.0, 4.0]})
        result = plotting.line(df, x="x", y="y", regression_line=True).save(
            "reg_no_bands", output_dir=tmp_path
        )
        assert result.png_path is not None and result.png_path.is_file()

    def test_matplotlib_line_scatter_dual_handle_object_numeric_strings_with_none(self, tmp_path):
        df = pd.DataFrame({
            "x": [1, 2, 3],
            "y": pd.Series(["1.5", None, "3.5"], dtype=object),
        })
        r_line = plotting.line(df, x="x", y="y").save("obj_line", output_dir=tmp_path)
        r_scatter = plotting.scatter(df, x="x", y="y").save("obj_scatter", output_dir=tmp_path)
        r_dual = plotting.dual(
            df, x="x", left_y="y", right_y="y", left_type="line", right_type="scatter"
        ).save("obj_dual", output_dir=tmp_path)
        assert r_line.png_path is not None and r_line.png_path.is_file()
        assert r_scatter.png_path is not None and r_scatter.png_path.is_file()
        assert r_dual.png_path is not None and r_dual.png_path.is_file()
