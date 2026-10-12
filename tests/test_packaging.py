"""Tests for what the distribution declares."""

from pathlib import Path

import tomli

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


def _project():
    with open(PYPROJECT, "rb") as f:
        return tomli.load(f)["project"]


def test_only_the_contributor_extra_remains():
    """The no-op [all], [data], [plotting] and [sphinx] aliases are retired."""
    assert set(_project()["optional-dependencies"]) == {"dev"}


def test_everything_is_a_base_dependency():
    """One install includes data loading, plotting, the docs toolchain and init."""
    names = {
        requirement.split(">")[0].split("<")[0].split("=")[0].strip().lower()
        for requirement in _project()["dependencies"]
    }
    assert {"polars", "plotly", "matplotlib", "sphinx", "cruft", "click"} <= names
