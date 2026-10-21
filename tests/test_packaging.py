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


def test_the_extras_are_a_store_a_warehouse_and_a_site_tool():
    """The no-op [all], [data], [plotting] and [sphinx] aliases are retired, and the
    contributor toolchain is the `dev` dependency group, not an extra.

    What remains is a kind of store that needs a cloud library the base
    install does not bring, a warehouse's driver, and a second site tool;
    each extra holds those libraries and nothing of the package itself, and
    Sphinx stays a base dependency.
    """
    extras = _project()["optional-dependencies"]
    assert set(extras) == {"s3", "databricks", "mkdocs"}  # the contributor toolchain is the `dev` dependency group
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


def test_the_build_backend_is_new_enough_for_the_license_files_list():
    """Found by a reviewer: `license-files = [...]` (PEP 639) is read from hatchling 1.27 on,
    and the build requirement named no version."""
    from packaging.requirements import Requirement
    from packaging.version import Version

    with open(PYPROJECT, "rb") as f:
        build_system = tomli.load(f)["build-system"]
    assert isinstance(_project()["license-files"], list)
    (hatchling,) = [Requirement(r) for r in build_system["requires"] if Requirement(r).name == "hatchling"]
    assert not hatchling.specifier.contains(Version("1.26.3"))
    assert hatchling.specifier.contains(Version("1.27.0"))


def test_no_stale_setuptools_manifest():
    """Found by a reviewer: a MANIFEST.in from the setuptools days named folders that do not
    exist; hatchling never read it. What the distribution holds is said in pyproject.toml and
    hatch_build.py, and nowhere else."""
    assert not (PYPROJECT.parent / "MANIFEST.in").exists()


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


class _App:
    """Stands in for hatchling's app, which a hook warns through."""

    def __init__(self):
        self.warnings = []

    def display_warning(self, message):
        self.warnings.append(message)


def _hook_for(hook_module, root, target_name):
    class Hook(hook_module.CustomBuildHook):
        def __init__(self):
            self.root, self.target_name, self.app = str(root), target_name, _App()

    return Hook()


def _run(hook_module, root, target_name, version="standard"):
    """Run the hook's initialize, and not its finalize; return the hook and its build data."""
    build_data = {"force_include": {}}
    built = _hook_for(hook_module, root, target_name)
    built.initialize(version, build_data)
    return built, build_data


def _recorded(build_data, target):
    """What the build puts in as built_from.txt at *target*, read from where the hook wrote it."""
    (source,) = [source for source, shipped in build_data["force_include"].items() if shipped == target]
    return Path(source).read_text()


@needs_git
def test_a_build_ships_the_template_files_git_tracks(hook, tmp_path):
    """Not a force-include of template/: a git-ignored `.env` there went into every wheel, and every project."""
    root = tmp_path / "checkout"
    _checkout(root)
    for target, inside in (("wheel", "chartbook/template"), ("sdist", "template")):
        built, build_data = _run(hook, root, target)
        shipped = sorted(path for path in build_data["force_include"].values() if path.startswith(inside))
        assert shipped == [
            f"{inside}/cookiecutter.json",
            f"{inside}/{{{{cookiecutter.project_slug}}}}/.gitignore",
            f"{inside}/{{{{cookiecutter.project_slug}}}}/README.md",
        ], target
        built.finalize("standard", build_data, "")
    # An editable install renders template/ from the checkout: the hook adds nothing
    _, build_data = _run(hook, root, "wheel", version="editable")
    assert build_data["force_include"] == {}


@needs_git
def test_the_commit_is_written_aside_and_never_into_the_tree(hook, tmp_path):
    """A file written into src/chartbook stayed behind when finalize did not run (Ctrl-C, an error,
    `--hooks-only`), a `git add -A` committed it, and every later build shipped a stale commit."""
    root = tmp_path / "checkout"
    head = _checkout(root)
    for target, shipped in (("sdist", "src/chartbook/built_from.txt"), ("wheel", "chartbook/built_from.txt")):
        built, build_data = _run(hook, root, target)
        assert _recorded(build_data, shipped).strip() == head
        # finalize not run, and the tree is as it was
        assert _git(root, "status", "--porcelain", "--untracked-files=all") == ""
    # Two builds at once each have their own
    first, first_data = _run(hook, root, "wheel")
    second, second_data = _run(hook, root, "wheel")
    first.finalize("standard", first_data, "")
    assert _recorded(second_data, "chartbook/built_from.txt").strip() == head


@needs_git
def test_a_stray_copy_in_the_tree_is_overridden(hook, tmp_path):
    """The force-included file takes the path; one left in src/chartbook does not ship in its place."""
    root = tmp_path / "checkout"
    head = _checkout(root)
    (root / "src" / "chartbook" / "built_from.txt").write_text("0" * 40 + "\n")
    built, build_data = _run(hook, root, "wheel")
    assert _recorded(build_data, "chartbook/built_from.txt").strip() == head
    built.finalize("standard", build_data, "")


@needs_git
def test_a_wheel_built_from_the_sdist_ships_the_sdists_commit(hook, tmp_path):
    """The sdist carries src/chartbook/built_from.txt; built from it, which is no checkout, the wheel ships it as it is."""
    root = tmp_path / "checkout"
    head = _checkout(root)
    built, build_data = _run(hook, root, "sdist")
    unpacked = tmp_path / "chartbook-0.2.0"
    shutil.copytree(root / "src", unpacked / "src")
    (unpacked / "PKG-INFO").write_text("Metadata-Version: 2.4\nName: chartbook\nVersion: 0.2.0\n")
    for source, shipped in build_data["force_include"].items():
        (unpacked / shipped).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, unpacked / shipped)
    built.finalize("standard", build_data, "")
    assert (unpacked / "src" / "chartbook" / "built_from.txt").read_text().strip() == head

    built, build_data = _run(hook, unpacked, "wheel")
    # Its own file goes in with the package; the hook adds only the sdist's template
    assert sorted(build_data["force_include"].values()) == [
        "chartbook/template/cookiecutter.json",
        "chartbook/template/{{cookiecutter.project_slug}}/.gitignore",
        "chartbook/template/{{cookiecutter.project_slug}}/README.md",
    ]
    assert (unpacked / "src" / "chartbook" / "built_from.txt").read_text().strip() == head
    built.finalize("standard", build_data, "")


def _sdist(folder, commit):
    """An unpacked sdist: its PKG-INFO, its code with the commit it records (None: no file), its template."""
    (folder / "src" / "chartbook").mkdir(parents=True)
    (folder / "PKG-INFO").write_text("Metadata-Version: 2.4\nName: chartbook\nVersion: 0.2.0\n")
    if commit is not None:
        (folder / "src" / "chartbook" / "built_from.txt").write_text(commit + "\n")
    (folder / "template").mkdir()
    (folder / "template" / "cookiecutter.json").write_text("{}\n")
    return folder


@pytest.mark.parametrize("commit", ["", None])
def test_a_build_stops_on_an_sdist_that_records_no_commit(hook, tmp_path, commit):
    """An sdist that records no commit (one made by hand, or by an older hook) builds no wheel: it says so."""
    root = _sdist(tmp_path / "chartbook-0.2.0", commit)
    with pytest.raises(RuntimeError, match="an sdist that records no commit.*Build the sdist from a git checkout"):
        _run(hook, root, "wheel")


def test_a_build_from_an_sdist_with_its_commit_goes_on(hook, tmp_path):
    """The path `uv build` and `python -m build` take for a release: the sdist, then a wheel from it."""
    root = _sdist(tmp_path / "chartbook-0.2.0", "a" * 40)
    built, build_data = _run(hook, root, "wheel")
    assert built.app.warnings == []
    assert sorted(build_data["force_include"].values()) == ["chartbook/template/cookiecutter.json"]


@needs_git
def test_an_sdist_unpacked_into_a_repository_of_its_own_is_the_sdist(hook, tmp_path):
    """A distribution's packaging may keep the unpacked sdist in git: its commit is the sdist's, not that HEAD."""
    root = _sdist(tmp_path / "chartbook-0.2.0", "a" * 40)
    for command in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "packaging"]):
        subprocess.run(["git", "-C", str(root), *command], check=True, capture_output=True)
    built, build_data = _run(hook, root, "wheel")
    assert built.app.warnings == []
    assert list(build_data["force_include"].values()) == ["chartbook/template/cookiecutter.json"]


@needs_git
def test_a_template_git_cannot_say_is_clean_records_no_commit(hook, tmp_path, monkeypatch):
    """If `git status` fails, whether template/ has changes is not known, so no commit is recorded."""
    root = tmp_path / "checkout"
    _checkout(root)
    real = hook.git
    monkeypatch.setattr(hook, "git", lambda where, *arguments: None if arguments[0] == "status" else real(where, *arguments))
    assert hook.commit_of(root) is None


@needs_git
def test_a_template_with_uncommitted_changes_stops_the_build(hook, tmp_path):
    """The commit must say what ships. An untracked file is never shipped, so it does not count."""
    root = tmp_path / "checkout"
    head = _checkout(root)
    (root / "template" / "notes.txt").write_text("mine\n")
    built, build_data = _run(hook, root, "wheel")
    assert _recorded(build_data, "chartbook/built_from.txt").strip() == head
    built.finalize("standard", build_data, "")
    (root / "template" / "cookiecutter.json").write_text("{}\n")
    with pytest.raises(RuntimeError, match="changes git has not committed.*Commit them"):
        _run(hook, root, "wheel")


@needs_git
def test_a_tracked_file_missing_from_disk_stops_the_build(hook, tmp_path, monkeypatch):
    """A sparse checkout, a file deleted and not committed, or git failing to list: the template would be short."""
    root = tmp_path / "checkout"
    _checkout(root)
    (root / "template" / "{{cookiecutter.project_slug}}" / "README.md").unlink()
    with pytest.raises(RuntimeError, match="not on disk"):
        _run(hook, root, "wheel")
    real = hook.git
    monkeypatch.setattr(hook, "git", lambda folder, *arguments: None if "ls-files" in arguments else real(folder, *arguments))
    with pytest.raises(RuntimeError, match="could not list"):
        _run(hook, root, "wheel")


def test_a_git_folder_git_cannot_read_stops_the_build_and_says_the_ways_out(hook, tmp_path):
    """`pip install .` in an image without git, or a folder git does not trust."""
    root = tmp_path / "checkout"
    (root / "src" / "chartbook").mkdir(parents=True)
    (root / "template").mkdir()
    (root / "template" / "cookiecutter.json").write_text("{}\n")
    (root / ".git").mkdir()
    with pytest.raises(RuntimeError, match="has a .git, and git cannot read it") as raised:
        _run(hook, root, "wheel")
    said = str(raised.value)
    assert "Install git" in said and "safe.directory" in said and "from an sdist" in said


def test_a_copy_that_is_neither_a_checkout_nor_an_sdist_stops_the_build(hook, tmp_path):
    """A source zip, or a Docker build whose .dockerignore leaves out .git: no commit can be told, and a stray
    built_from.txt in the tree never ships as if it were one."""
    root = tmp_path / "copy"
    (root / "src" / "chartbook").mkdir(parents=True)
    (root / "src" / "chartbook" / "built_from.txt").write_text("0" * 40 + "\n")
    (root / "template").mkdir()
    (root / "template" / "cookiecutter.json").write_text("{}\n")
    with pytest.raises(RuntimeError, match="neither a git checkout nor an sdist.*clone of the repository.*PyPI"):
        _run(hook, root, "wheel")


def _dodo():
    import importlib.util

    spec = importlib.util.spec_from_file_location("chartbook_dodo", PYPROJECT.parent / "dodo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_release_build_task_is_a_plain_build():
    """`doit build_package` is `uv build`, which calls the hatchling backend: the hook itself stops a build
    that cannot record its commit, so there is no setting to remember (the maintainer asked why there was
    one; there is not)."""
    assert _dodo().task_build_package()["actions"] == ["uv build"]


def test_plain_doit_runs_each_suite_once():
    """The matrix includes the default Python, so `test` is not a default task beside `test_all`."""
    assert _dodo().DOIT_CONFIG["default_tasks"] == ["build", "test_all"]


def test_the_dev_group_gives_the_suite_what_the_matrix_gives_it():
    """`uv run pytest` and `hatch test` must see the same packages: the `dev` group covers every
    extra dependency of the hatch-test environment (names, not pins)."""
    import re

    with open(PYPROJECT, "rb") as f:
        document = tomli.load(f)

    def names(requirements):
        # The distribution name alone, as PEP 503 compares it
        return {re.split(r"[\[<>=!~; ]", requirement, maxsplit=1)[0].lower().replace("_", "-") for requirement in requirements}

    matrix = names(document["tool"]["hatch"]["envs"]["hatch-test"]["extra-dependencies"])
    dev = names(document["dependency-groups"]["dev"])
    assert matrix <= dev, f"missing from the dev group: {sorted(matrix - dev)}"
    assert {"doit", "hatch", "pytest"} <= dev


def test_the_hook_and_init_name_the_file_alike(hook):
    from chartbook import scaffold

    assert hook.BUILT_FROM == scaffold.BUILT_FROM




def test_every_module_compiles_without_a_warning():
    """Found while smoke-testing the 0.2.0 wheel: a docstring held ``\\``` in an ordinary string, and the
    first import printed "invalid escape sequence" to every user (a SyntaxWarning, which a later Python
    makes an error). The suite filters warnings, so it is compiled here with them as errors."""
    import warnings

    for path in sorted((PYPROJECT.parent / "src" / "chartbook").rglob("*.py")):
        if "{{" in str(path):  # the project template's Jinja, rendered before it is Python
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
