"""Tests for the plotting backend interface as documented.

``docs_src/guide/plotting-backends.md`` tells a third-party author how to
write and register a backend, and includes ``docs_src/_examples/
vegalite_backend.py`` as its worked example. These tests run that exact
file, registered through a real entry point, so the guide cannot drift from
the code without a test failing.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from chartbook.plotting import ChartConfig, DualAxisConfig, OverlayConfig
from chartbook.plotting import backends
from chartbook.plotting.backends import (
    BaseBackend,
    PlottingBackend,
    get_backend,
    list_backends,
    register_backend,
)

EXAMPLE = Path(__file__).parent.parent / "docs_src" / "_examples" / "vegalite_backend.py"
ENTRY_POINT_GROUP = "chartbook_plotting"


@pytest.fixture
def fresh_registry(monkeypatch):
    """Start each test with no plugin manager, as a new process would."""
    monkeypatch.setattr(backends, "_pm", None)
    yield
    monkeypatch.setattr(backends, "_pm", None)


@pytest.fixture
def installed_example(tmp_path, monkeypatch, fresh_registry):
    """Install the guide's example the way pip would: a module on the path
    plus a ``.dist-info`` whose entry points name it."""
    site = tmp_path / "site-packages"
    dist_info = site / "chartbook_vegalite-0.1.dist-info"
    dist_info.mkdir(parents=True)
    (site / "chartbook_vegalite.py").write_text(EXAMPLE.read_text())
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: chartbook-vegalite\nVersion: 0.1\n"
    )
    # Exactly the registration the guide tells an author to write
    (dist_info / "entry_points.txt").write_text(
        f"[{ENTRY_POINT_GROUP}]\nvegalite = chartbook_vegalite:backend\n"
    )
    monkeypatch.syspath_prepend(str(site))
    yield
    sys.modules.pop("chartbook_vegalite", None)


@pytest.fixture
def df():
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"]),
            "gdp": [1.0, 2.0, 3.0],
            "cpi": [3.0, 2.5, 2.0],
            "sector": ["a", "b", "c"],
        }
    )


def _load_example():
    spec = importlib.util.spec_from_file_location("vegalite_backend_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestContract:
    def test_builtin_backends_satisfy_the_protocol(self, fresh_registry):
        for name in ("plotly", "matplotlib"):
            backend = get_backend(name)
            assert isinstance(backend, PlottingBackend)
            assert isinstance(backend, BaseBackend)
            assert backend.name == name

    def test_base_backend_requires_the_five_chart_types_and_a_name(self):
        assert BaseBackend.__abstractmethods__ == {
            "name",
            "create_line",
            "create_bar",
            "create_scatter",
            "create_pie",
            "create_area",
        }

    def test_incomplete_backend_cannot_be_instantiated(self):
        class Incomplete(BaseBackend):
            name = "incomplete"

            def create_line(self, df, config, overlay, output_path, size):
                pass

        with pytest.raises(TypeError, match="abstract"):
            Incomplete()

    def test_example_is_a_complete_backend(self):
        backend = _load_example().backend
        assert isinstance(backend, BaseBackend)
        assert isinstance(backend, PlottingBackend)
        assert backend.name == "vegalite"

    def test_dual_axis_is_optional(self, df, tmp_path):
        backend = _load_example().backend
        config = DualAxisConfig(
            x="date", left_y=["gdp"], right_y=["cpi"], left_type="bar", right_type="line"
        )
        with pytest.raises(NotImplementedError, match="vegalite"):
            backend.create_dual_axis(df, config, OverlayConfig(), tmp_path / "x.json", (8, 6))


class TestEntryPointRegistration:
    def test_installed_backend_is_discovered(self, installed_example):
        assert "vegalite" in list_backends()
        backend = get_backend("vegalite")
        assert type(backend).__name__ == "VegaLiteBackend"
        assert backend.name == "vegalite"

    def test_builtins_remain_available_alongside_it(self, installed_example):
        assert {"plotly", "matplotlib", "vegalite"} <= set(list_backends())
        assert get_backend("plotly").name == "plotly"

    def test_unknown_backend_lists_what_is_available(self, installed_example):
        with pytest.raises(ValueError, match="Unknown backend: bokeh") as excinfo:
            get_backend("bokeh")
        assert "vegalite" in str(excinfo.value)

    def test_not_registered_until_installed(self, fresh_registry):
        with pytest.raises(ValueError, match="Unknown backend: vegalite"):
            get_backend("vegalite")


class TestRegisterBackend:
    def test_register_an_instance_directly(self, fresh_registry):
        register_backend(_load_example().VegaLiteBackend())
        assert get_backend("vegalite").name == "vegalite"

    def test_register_under_another_name(self, fresh_registry):
        backend = _load_example().VegaLiteBackend()
        register_backend(backend, name="vl")
        assert get_backend("vl") is backend


class TestUsingABackend:
    """The calls shown under "Using a backend" in the guide."""

    @pytest.mark.parametrize(
        "chart_type, mark",
        [("line", "line"), ("bar", "bar"), ("scatter", "point"), ("area", "area")],
    )
    def test_create_chart_routes_on_chart_type(
        self, installed_example, df, tmp_path, chart_type, mark
    ):
        config = ChartConfig(
            chart_type=chart_type, x="date", y=["gdp", "cpi"], title="Growth"
        )
        output_path = tmp_path / "_output" / f"{chart_type}.vl.json"

        get_backend("vegalite").create_chart(
            df, config, OverlayConfig(), output_path, size=(8, 6)
        )

        spec = json.loads(output_path.read_text())
        assert spec["mark"] == mark
        assert spec["title"] == "Growth"
        assert (spec["width"], spec["height"]) == (768, 576)
        assert spec["encoding"]["x"]["field"] == "date"
        # Both y columns are plotted, as separate series
        assert spec["transform"] == [{"fold": ["gdp", "cpi"], "as": ["series", "value"]}]
        assert len(spec["data"]["values"]) == 3
        assert spec["data"]["values"][0]["date"].startswith("2024-01-01")

    def test_pie_uses_names_and_values(self, installed_example, df, tmp_path):
        config = ChartConfig(
            chart_type="pie", x="sector", y=["gdp"], names="sector", values="gdp"
        )
        output_path = tmp_path / "pie.vl.json"
        get_backend("vegalite").create_chart(df, config, OverlayConfig(), output_path, (6, 6))
        spec = json.loads(output_path.read_text())
        assert spec["mark"] == "arc"
        assert spec["encoding"]["theta"]["field"] == "gdp"
        assert spec["encoding"]["color"]["field"] == "sector"

    def test_output_directory_is_created(self, installed_example, df, tmp_path):
        config = ChartConfig(chart_type="line", x="date", y=["gdp"])
        output_path = tmp_path / "does" / "not" / "exist" / "chart.json"
        get_backend("vegalite").create_line(df, config, OverlayConfig(), output_path, (8, 6))
        assert output_path.is_file()

    def test_unknown_chart_type_is_rejected(self, installed_example, df, tmp_path):
        config = ChartConfig(chart_type="radar", x="date", y=["gdp"])
        with pytest.raises(ValueError, match="Unknown chart type: radar"):
            get_backend("vegalite").create_chart(
                df, config, OverlayConfig(), tmp_path / "x.json", (8, 6)
            )

    def test_configs_are_importable_from_the_public_package(self):
        import chartbook.plotting as plotting

        for name in ("ChartConfig", "OverlayConfig", "DualAxisConfig"):
            assert name in plotting.__all__


class TestGuideMatchesTheCode:
    """Facts the guide states that would silently go stale."""

    GUIDE = EXAMPLE.parent.parent / "guide" / "plotting-backends.md"

    def test_guide_includes_the_tested_example(self):
        assert "{literalinclude} ../_examples/vegalite_backend.py" in self.GUIDE.read_text()

    def test_entry_point_group_name(self, fresh_registry):
        assert backends.get_plugin_manager().project_name == ENTRY_POINT_GROUP
        assert f"`{ENTRY_POINT_GROUP}`" in self.GUIDE.read_text()

    @pytest.mark.parametrize("config_class", [ChartConfig, OverlayConfig, DualAxisConfig])
    def test_every_config_field_is_documented(self, config_class):
        import dataclasses

        guide = self.GUIDE.read_text()
        section = guide.split(f"### `{config_class.__name__}`", 1)[1].split("\n## ", 1)[0]
        section = section.split("\n### ", 1)[0]
        for field in dataclasses.fields(config_class):
            assert f"`{field.name}`" in section, (
                f"{config_class.__name__}.{field.name} is not in the guide"
            )
