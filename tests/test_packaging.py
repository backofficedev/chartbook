"""Tests for what the distribution declares."""

from pathlib import Path

import tomli

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


def _project():
    with open(PYPROJECT, "rb") as f:
        return tomli.load(f)["project"]


def test_the_extras_are_the_contributor_one_a_store_a_warehouse_and_a_site_tool():
    """The no-op [all], [data], [plotting] and [sphinx] aliases are retired.

    What remains is contributor tooling, a kind of store that needs a cloud
    library the base install does not bring, a warehouse's driver, and a
    second site tool; each extra holds those libraries and nothing of the
    package itself, and Sphinx stays a base dependency.
    """
    extras = _project()["optional-dependencies"]
    assert set(extras) == {"dev", "s3", "databricks", "mkdocs"}
    assert [r.split(">")[0] for r in extras["s3"]] == ["boto3"]
    assert [r.split(">")[0] for r in extras["databricks"]] == ["databricks-sql-connector[pyarrow]"]
    assert [r.split(">")[0] for r in extras["mkdocs"]] == ["mkdocs", "mkdocs-material", "mkdocs-jupyter"]


def test_a_kind_of_store_is_an_entry_point():
    """A store is found by the scheme of its URL; the S3 store is registered under `s3`."""
    assert _project()["entry-points"]["chartbook.stores"] == {"s3": "chartbook.stores.s3:S3Store"}


def test_a_backend_is_an_entry_point():
    """A source's backend is found by its name; Databricks is registered under `databricks`."""
    assert _project()["entry-points"]["chartbook.backends"] == {
        "databricks": "chartbook.backends.databricks:DatabricksBackend"
    }


def test_everything_is_a_base_dependency():
    """One install includes data loading, plotting, the docs toolchain and init."""
    names = {
        requirement.split(">")[0].split("<")[0].split("=")[0].strip().lower()
        for requirement in _project()["dependencies"]
    }
    assert {"polars", "plotly", "matplotlib", "sphinx", "cruft", "click"} <= names


def _build_config():
    with open(PYPROJECT, "rb") as f:
        return tomli.load(f)["tool"]["hatch"]["build"]


def test_the_wheel_and_the_sdist_carry_the_project_template():
    """`chartbook init` renders the template that came with the package (chartbook.scaffold.find_template)."""
    build = _build_config()
    assert build["targets"]["wheel"]["force-include"] == {"template": "chartbook/template"}
    # A wheel built from the sdist has it to take
    assert build["targets"]["sdist"]["force-include"] == {"template": "template"}
    assert (PYPROJECT.parent / "template" / "cookiecutter.json").is_file()


def test_cookiecutter_is_a_dependency_of_its_own():
    """`chartbook init` renders with it directly, and the template's questions need 2.2's __prompts__."""
    assert "cookiecutter>=2.2" in _project()["dependencies"]


def _hook_module(monkeypatch):
    """hatch_build.py, loaded without hatchling, which only a build has."""
    import importlib.util
    import sys
    import types

    interface = types.ModuleType("hatchling.builders.hooks.plugin.interface")
    interface.BuildHookInterface = object
    for name in ("hatchling", "hatchling.builders", "hatchling.builders.hooks", "hatchling.builders.hooks.plugin"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "hatchling.builders.hooks.plugin.interface", interface)
    spec = importlib.util.spec_from_file_location("hatch_build", PYPROJECT.parent / "hatch_build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_build_records_the_commit_it_is_built_from(monkeypatch, tmp_path):
    """The build hook puts `built_from.txt` beside the modules; the version is not touched."""
    import shutil
    import subprocess

    import pytest

    from chartbook import scaffold

    assert "custom" in _build_config()["hooks"]
    hook_module = _hook_module(monkeypatch)
    assert hook_module.BUILT_FROM == scaffold.BUILT_FROM
    if shutil.which("git") is None:
        pytest.skip("git not installed")

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Test Author")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")

    def git(*arguments):
        return subprocess.run(["git", *arguments], cwd=checkout, capture_output=True, text=True, check=True).stdout

    git("init", "--quiet")
    (checkout / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    git("add", "-A")
    git("commit", "--quiet", "-m", "One")
    head = git("rev-parse", "HEAD").strip()

    class Hook(hook_module.CustomBuildHook):
        def __init__(self, target_name):
            self.root, self.target_name = str(checkout), target_name

    for target, inside in (("wheel", "chartbook"), ("sdist", "src/chartbook")):
        hook, build_data = Hook(target), {"force_include": {}}
        hook.initialize("standard", build_data)
        ((written, shipped),) = build_data["force_include"].items()
        assert shipped == f"{inside}/built_from.txt"
        assert Path(written).read_text().strip() == head
        hook.finalize("standard", build_data, "")
        assert not Path(written).exists()

    # An editable install asks git at run time; a folder that is not a checkout knows nothing
    build_data = {"force_include": {}}
    Hook("wheel").initialize("editable", build_data)
    assert build_data["force_include"] == {}
    (tmp_path / "unpacked").mkdir()
    assert hook_module.commit_of(tmp_path / "unpacked") is None
