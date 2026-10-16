"""Tests for what the distribution declares."""

from pathlib import Path

import tomli

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


def _project():
    with open(PYPROJECT, "rb") as f:
        return tomli.load(f)["project"]


def test_the_extras_are_the_contributor_one_a_store_and_a_site_tool():
    """The no-op [all], [data], [plotting] and [sphinx] aliases are retired.

    What remains is contributor tooling, a kind of store that needs a cloud
    library the base install does not bring, and a second site tool; each
    extra holds those libraries and nothing of the package itself, and
    Sphinx stays a base dependency.
    """
    extras = _project()["optional-dependencies"]
    assert set(extras) == {"dev", "s3", "mkdocs"}
    assert [r.split(">")[0] for r in extras["s3"]] == ["boto3"]
    assert [r.split(">")[0] for r in extras["mkdocs"]] == ["mkdocs", "mkdocs-material", "mkdocs-jupyter"]


def test_a_kind_of_store_is_an_entry_point():
    """A store is found by the scheme of its URL; the S3 store is registered under `s3`."""
    assert _project()["entry-points"]["chartbook.stores"] == {"s3": "chartbook.stores.s3:S3Store"}


def test_everything_is_a_base_dependency():
    """One install includes data loading, plotting, the docs toolchain and init."""
    names = {
        requirement.split(">")[0].split("<")[0].split("=")[0].strip().lower()
        for requirement in _project()["dependencies"]
    }
    assert {"polars", "plotly", "matplotlib", "sphinx", "cruft", "click"} <= names
