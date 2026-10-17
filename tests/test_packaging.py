"""Tests for what the distribution declares, and the build hook that puts the template in it."""

import shutil
import subprocess
from pathlib import Path

import pytest
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


def test_the_template_is_put_in_by_the_build_hook_not_a_force_include():
    """A force-include shipped whatever was in template/, git-ignored files too, and an editable
    install copied it into site-packages; the hook ships what git tracks, for a wheel or an sdist."""
    build = _build_config()
    assert "custom" in build["hooks"]
    for target in ("wheel", "sdist"):
        assert "force-include" not in build.get("targets", {}).get(target, {}), target
    assert "force-include" not in build
    assert (PYPROJECT.parent / "template" / "cookiecutter.json").is_file()


def test_the_sdist_keeps_the_source_layout():
    """A wheel built from the sdist is the wheel built from the checkout.

    `packages = ["src/chartbook"]` for every target, and a `sources`
    remapping, made the sdist strip `src/` (hatchling derives a `src/` -> ``
    source from `packages`, and rewrites every path through it); the
    sdist's own pyproject then pointed the wheel at a `src/chartbook` that
    was not there, and the wheel had no code. Only the wheel collapses
    `src/`, by its own `packages`.
    """
    import pathspec

    build = _build_config()
    for option in ("packages", "include", "sources", "only-include"):
        assert option not in build, f"[tool.hatch.build] {option} reaches the sdist too"
    wheel, sdist = build["targets"]["wheel"], build["targets"]["sdist"]
    assert wheel["packages"] == ["src/chartbook"]
    assert "sources" not in wheel
    # Nothing that would make hatchling rewrite the sdist's paths
    assert "packages" not in sdist and "sources" not in sdist
    included = pathspec.GitIgnoreSpec.from_lines(sdist["include"])
    for path in ("src/chartbook/__init__.py", "src/chartbook/skills/SKILL.md", "src/chartbook/built_from.txt"):
        assert included.match_file(path), path
    # The template comes in from hatch_build.py, only the files git tracks
    assert not included.match_file("template/cookiecutter.json")


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


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture
def hook(monkeypatch):
    """The build hook's module, with git insulated from the developer's own configuration."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Test Author")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")
    return _hook_module(monkeypatch)


def _git(folder, *arguments):
    return subprocess.run(["git", *arguments], cwd=folder, capture_output=True, text=True, check=True).stdout


def _checkout(folder: Path) -> str:
    """A repository like this one: `src/chartbook/` and a `template/` with an ignored file; its HEAD."""
    (folder / "src" / "chartbook").mkdir(parents=True)
    (folder / "src" / "chartbook" / "__init__.py").write_text("")
    slug = folder / "template" / "{{cookiecutter.project_slug}}"
    slug.mkdir(parents=True)
    (folder / "template" / "cookiecutter.json").write_text('{"project_slug": "x"}\n')
    (slug / "README.md").write_text("# {{ cookiecutter.project_slug }}\n")
    (slug / ".gitignore").write_text(".env\n")
    _git(folder, "init", "--quiet")
    _git(folder, "add", "-A")
    _git(folder, "commit", "--quiet", "-m", "One")
    # Never tracked: the template author's own secrets
    (slug / ".env").write_text("KEY=secret\n")
    return _git(folder, "rev-parse", "HEAD").strip()


def _hook_for(hook_module, root, target_name):
    class Hook(hook_module.CustomBuildHook):
        def __init__(self):
            self.root, self.target_name = str(root), target_name

    return Hook()


def _run(hook_module, root, target_name, version="standard"):
    """Run the hook's initialize; return the hook and its build data."""
    build_data = {"force_include": {}}
    built = _hook_for(hook_module, root, target_name)
    built.initialize(version, build_data)
    return built, build_data


@needs_git
def test_a_build_ships_the_template_files_git_tracks(hook, tmp_path):
    """Not a force-include of template/: a git-ignored `.env` there went into every wheel, and every project."""
    root = tmp_path / "checkout"
    _checkout(root)
    for target, inside in (("wheel", "chartbook/template"), ("sdist", "template")):
        built, build_data = _run(hook, root, target)
        shipped = sorted(build_data["force_include"].values())
        assert shipped == [
            f"{inside}/cookiecutter.json",
            f"{inside}/{{{{cookiecutter.project_slug}}}}/.gitignore",
            f"{inside}/{{{{cookiecutter.project_slug}}}}/README.md",
        ], target
        built.finalize("standard", build_data, "")
    # An editable install renders template/ from the checkout: the hook adds nothing
    _, build_data = _run(hook, root, "wheel", version="editable")
    assert build_data["force_include"] == {}
    assert not (root / "src" / "chartbook" / "built_from.txt").exists()


@needs_git
def test_the_commit_goes_where_a_wheel_built_from_the_sdist_finds_it(hook, tmp_path):
    """`uv build` made an sdist with `chartbook/built_from.txt` at its root, and a wheel from it had none."""
    root = tmp_path / "checkout"
    head = _checkout(root)
    recorded = root / "src" / "chartbook" / "built_from.txt"

    # The sdist: the file is in the source tree, under src/chartbook, for the build
    built, build_data = _run(hook, root, "sdist")
    assert recorded.read_text().strip() == head
    assert str(recorded) not in build_data["force_include"]
    # ...laid out as the sdist is
    unpacked = tmp_path / "chartbook-0.2.0"
    shutil.copytree(root / "src", unpacked / "src")
    for source, shipped in build_data["force_include"].items():
        (unpacked / shipped).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, unpacked / shipped)
    built.finalize("standard", build_data, "")
    assert not recorded.exists()

    # The wheel, from the unpacked sdist, which is no checkout: its file is kept, and its template shipped
    built, build_data = _run(hook, unpacked, "wheel")
    assert (unpacked / "src" / "chartbook" / "built_from.txt").read_text().strip() == head
    assert sorted(build_data["force_include"].values()) == [
        "chartbook/template/cookiecutter.json",
        "chartbook/template/{{cookiecutter.project_slug}}/.gitignore",
        "chartbook/template/{{cookiecutter.project_slug}}/README.md",
    ]
    built.finalize("standard", build_data, "")
    assert (unpacked / "src" / "chartbook" / "built_from.txt").is_file()

    # A packager who makes the unpacked sdist a repository of their own: the file is theirs to keep
    _git(unpacked, "init", "--quiet")
    _git(unpacked, "add", "-A")
    _git(unpacked, "commit", "--quiet", "-m", "Packaging")
    built, build_data = _run(hook, unpacked, "wheel")
    assert (unpacked / "src" / "chartbook" / "built_from.txt").read_text().strip() == head
    built.finalize("standard", build_data, "")
    assert (unpacked / "src" / "chartbook" / "built_from.txt").is_file()


@needs_git
def test_a_leftover_from_an_earlier_build_of_the_checkout_is_replaced(hook, tmp_path):
    root = tmp_path / "checkout"
    head = _checkout(root)
    recorded = root / "src" / "chartbook" / "built_from.txt"
    recorded.write_text("0" * 40 + "\n")
    built, build_data = _run(hook, root, "wheel")
    assert recorded.read_text().strip() == head
    built.finalize("standard", build_data, "")


@needs_git
def test_a_template_with_uncommitted_changes_is_recorded_at_no_commit(hook, tmp_path):
    root = tmp_path / "checkout"
    _checkout(root)
    (root / "template" / "cookiecutter.json").write_text("{}\n")
    built, build_data = _run(hook, root, "wheel")
    assert not (root / "src" / "chartbook" / "built_from.txt").exists()
    built.finalize("standard", build_data, "")


def test_a_git_folder_git_cannot_read_stops_the_build(hook, tmp_path):
    """"Dubious ownership", a broken checkout: a build of a checkout never records nothing without saying so."""
    root = tmp_path / "checkout"
    (root / "src" / "chartbook").mkdir(parents=True)
    (root / "template").mkdir()
    (root / ".git").mkdir()
    with pytest.raises(RuntimeError, match="has a .git, and git cannot read it"):
        _run(hook, root, "wheel")


def test_the_hook_and_init_name_the_file_alike(hook):
    from chartbook import scaffold

    assert hook.BUILT_FROM == scaffold.BUILT_FROM

