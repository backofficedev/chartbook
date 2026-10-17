"""Tests for ``chartbook init --git`` / ``--github``.

``git`` and ``gh`` are replaced by a fake ``subprocess.run``, and rendering
the template by a fake ``scaffold.render``; together they record every
command, so these tests assert on what would be run and in what order. The
tests at the end use real git, and render the real template, which comes
with the package.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from chartbook import scaffold
from chartbook.cli import main
from chartbook.identity import clear_git_remote_cache
from chartbook.manifest import load_manifest

#: A commit the stand-in for rendering says the template came from
COMMIT = "0123456789abcdef0123456789abcdef01234567"


class FakeTools:
    """Stands in for rendering the template, and for git and gh.

    Rendering (``scaffold.render``, recorded as the command ``["render"]``)
    makes a project directory named by ``project_name``, as the real one
    names it from the user's answers. Any command whose leading words are in
    ``failing`` returns a nonzero exit code; a failing ``render`` raises what
    cookiecutter raises when a hook stops it.
    """

    def __init__(self, cwd: Path):
        self.cwd = cwd
        self.calls: list[tuple[list[str], Path]] = []
        self.installed = {"git", "gh"}
        self.failing: dict[tuple[str, ...], str] = {}
        self.project_name = "my_data_science_project"
        # The commit the template came from, as this ChartBook knows it
        self.commit = COMMIT
        # Whether that commit is on a remote branch of the checkout, if that can be told
        self.pushed = True
        self.remote_url = None
        # The repository the working directory is inside, if any
        self.outer_repo = None
        # The user's init.defaultBranch, if they have set one
        self.configured_branch = None

    # -- the two things the code under test calls -------------------------

    def which(self, name):
        return f"/usr/bin/{name}" if name in self.installed else None

    def render_template(self, output_dir, **kwargs):
        from cookiecutter.exceptions import FailedHookException

        if (Path(output_dir) / self.project_name).exists():
            raise scaffold.ProjectExistsError(Path(output_dir) / self.project_name)
        result = self.run(["render"], cwd=output_dir)
        if result.returncode != 0:
            raise FailedHookException("Hook script failed (exit status: 1)")
        return scaffold.Rendered(
            Path(output_dir) / self.project_name,
            self.commit,
            self.pushed,
            why="" if self.commit else "this ChartBook was built without recording it",
            answers={"project_name": "Rates' Study", "project_slug": self.project_name},
        )

    def run(self, command, cwd=None, **kwargs):
        cwd = Path(cwd) if cwd is not None else self.cwd
        self.calls.append((list(command), cwd))

        for prefix, message in self.failing.items():
            if tuple(command[: len(prefix)]) == prefix:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr=message)

        if command[:2] == ["git", "rev-parse"]:
            if self.outer_repo is None:
                return subprocess.CompletedProcess(
                    command, 128, stdout="", stderr="fatal: not a git repository"
                )
            return subprocess.CompletedProcess(
                command, 0, stdout=f"{self.outer_repo}\n", stderr=""
            )
        if command[0] == "render":
            project = self.cwd / self.project_name
            project.mkdir()
            (project / ".cruft.json").write_text("{}")
            (project / ".gitignore").write_text(".env\n_data/\n")
            (project / "README.md").write_text("# My Data Science Project\n")
            (project / "chartbook.toml").write_text(
                '[project]\nname = "My Data Science Project"\n'
            )
        if command[:3] == ["gh", "repo", "create"]:
            self.remote_url = f"https://github.com/octo/{command[3]}.git"
            # As the real gh prints: the URL, then git's note about the push
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=f"https://github.com/octo/{command[3]}\n"
                "branch 'main' set up to track 'origin/main'.\n",
                stderr="",
            )
        if command[:3] == ["git", "config", "--get"] and "init.defaultBranch" in command:
            if self.configured_branch:
                return subprocess.CompletedProcess(
                    command, 0, stdout=f"{self.configured_branch}\n", stderr=""
                )
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
        # What chartbook.identity asks git when deriving a pipeline's scope
        if command[:2] == ["git", "-C"] and "remote.origin.url" in command:
            if self.remote_url:
                return subprocess.CompletedProcess(
                    command, 0, stdout=self.remote_url + "\n", stderr=""
                )
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    # -- what tests ask about ---------------------------------------------

    def commands(self, program=None):
        return [c for c, _ in self.calls if program is None or c[0] == program]

    def index_of(self, *prefix):
        for i, (command, _) in enumerate(self.calls):
            if tuple(command[: len(prefix)]) == prefix:
                return i
        raise AssertionError(f"{prefix} was never run; ran {self.commands()}")

    def ran(self, *prefix):
        return any(tuple(c[: len(prefix)]) == prefix for c, _ in self.calls)

    @property
    def project(self):
        return self.cwd / self.project_name


@pytest.fixture
def tools(tmp_path, monkeypatch):
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    monkeypatch.delenv("GH_HOST", raising=False)
    fake = FakeTools(workdir.resolve())
    monkeypatch.setattr(subprocess, "run", fake.run)
    monkeypatch.setattr(shutil, "which", fake.which)
    monkeypatch.setattr(scaffold, "render", fake.render_template)
    clear_git_remote_cache()
    yield fake
    clear_git_remote_cache()


def _init(*args):
    return CliRunner().invoke(main, ["init", *args])


class TestPlainInit:
    def test_only_renders(self, tools):
        result = _init()
        assert result.exit_code == 0, result.output
        assert tools.commands() == [["render"]]
        assert "cruft update" not in result.output

    def test_the_template_is_in_this_repository(self):
        """Where `chartbook init` says it is, there is a cookiecutter template."""
        template = Path(__file__).parent.parent / scaffold.TEMPLATE_DIRECTORY
        assert (template / "cookiecutter.json").is_file()
        assert (template / "{{cookiecutter.project_slug}}" / "chartbook.toml").is_file()
        # ...and it is the one this ChartBook, run from its source, renders
        assert scaffold.find_template() == template.resolve()

    def test_with_no_commit_known_it_says_how_to_link_the_project_later(self, tools):
        """A .cruft.json naming no commit is up to date for `cruft check`, and `cruft update` does nothing."""
        tools.commit = None
        result = _init()
        assert result.exit_code == 0, result.output
        said = " ".join(result.output.split())
        # Why, as it is: not a guess between two causes
        assert "its template is at (this ChartBook was built without recording it)" in said
        assert "so my_data_science_project has no .cruft.json" in said
        # With the answers given here, so none is retyped, or typed differently
        (command,) = [line.strip() for line in result.output.splitlines() if line.strip().startswith("cruft link")]
        import json
        import shlex

        words = shlex.split(command.replace("<commit>", "abc123"))
        assert words[:9] == [
            "cruft", "link", "https://github.com/backofficedev/chartbook", "--directory", "template",
            "--checkout", "abc123", "--no-input", "--extra-context",
        ]
        assert json.loads(words[9]) == {"project_name": "Rates' Study", "project_slug": "my_data_science_project"}

    def test_a_commit_on_no_remote_branch_is_said(self, tools):
        tools.pushed = False
        result = _init()
        assert result.exit_code == 0, result.output
        said = " ".join(result.output.split())
        assert (
            f"the template's commit, {COMMIT[:12]}, is on no branch of a remote that is "
            f"https://github.com/backofficedev/chartbook, and in no tag" in said
        )
        assert "may not be on GitHub" in said

    def test_a_folder_that_is_there_already_is_said_as_that(self, tools):
        (tools.cwd / tools.project_name).mkdir()
        result = _init()
        assert result.exit_code == 1
        said = " ".join(result.output.split())
        assert f"{tools.cwd / tools.project_name} is there already, so nothing was changed" in said
        assert "Error: Error" not in said
        assert "If the folder name was refused" not in said

    def test_git_and_github_are_off_by_default(self, tools):
        _init()
        assert tools.commands("git") == []
        assert tools.commands("gh") == []

    @pytest.mark.parametrize("flags", [(), ("--git",)])
    def test_a_refused_folder_name_is_said_again_last(self, tools, flags):
        """The template's own message is above cookiecutter's (cruft's traceback was about 118 lines)."""
        tools.failing[("render",)] = "Traceback (most recent call last): ..."
        result = _init(*flags)
        assert result.exit_code == 1
        # Enter is not always the answer: "2024 Rates" makes `2024_rates`, refused too
        assert result.output.strip().splitlines()[-1] == (
            "If the folder name was refused, run `chartbook init` again and, at the second "
            "question, press Enter, or type a name of lowercase letters, digits and `_`."
        )

    def test_visibility_without_github_is_a_usage_error(self, tools):
        for flag in ("--public", "--private"):
            result = _init(flag)
            assert result.exit_code == 2
            assert "only applies with --github" in result.output
        assert tools.commands() == []
        result = _init("--git", "--public")
        assert result.exit_code == 2


class TestGit:
    def test_inits_and_commits_in_the_new_project(self, tools):
        result = _init("--git")
        assert result.exit_code == 0, result.output
        in_project = [c for c, cwd in tools.calls if cwd == tools.project]
        assert in_project == [
            ["git", "config", "--get", "init.defaultBranch"],
            ["git", "init", "--initial-branch=main"],
            ["git", "add", "--all"],
            ["git", "commit", "-m", "Initial commit from chartbook init"],
        ]
        assert f"Initialized a git repository in {tools.project}" in result.output
        assert tools.commands("gh") == []

    def test_first_branch_is_main_unless_the_user_configured_one(self, tools):
        _init("--git")
        assert tools.ran("git", "init", "--initial-branch=main")

    def test_a_configured_default_branch_is_respected(self, tools):
        tools.configured_branch = "trunk"
        _init("--git")
        inits = [c for c in tools.commands("git") if c[1] == "init"]
        assert inits == [["git", "init"]]

    def test_old_git_without_the_branch_option_still_works(self, tools):
        tools.failing[("git", "init", "--initial-branch=main")] = "unknown option"
        result = _init("--git")
        assert result.exit_code == 0, result.output
        assert ["git", "init"] in tools.commands("git")
        assert tools.ran("git", "commit")

    def test_git_is_set_up_in_the_project_rendered(self, tools):
        """The directory is named by an answer at the prompt; rendering says which it is."""
        tools.project_name = "whatever_the_user_typed"
        # A project rendered earlier must not be mistaken for the new one
        older = tools.cwd / "an_older_project"
        older.mkdir()
        (older / ".cruft.json").write_text("{}")
        (tools.cwd / "unrelated_dir").mkdir()

        result = _init("--git")
        assert result.exit_code == 0, result.output
        git_dirs = {cwd for c, cwd in tools.calls if c[:2] == ["git", "init"]}
        assert git_dirs == {tools.cwd / "whatever_the_user_typed"}

    def test_checks_git_before_rendering(self, tools):
        _init("--git")
        assert tools.index_of("git", "var", "GIT_AUTHOR_IDENT") < tools.index_of("render")

    def test_without_git_installed_nothing_is_created(self, tools):
        tools.installed = {"gh"}
        result = _init("--git")
        assert result.exit_code == 1
        assert "git is not installed" in result.output
        assert "https://git-scm.com/downloads" in result.output
        assert not tools.ran("render")
        assert list(tools.cwd.iterdir()) == []

    def test_without_a_git_identity_nothing_is_created(self, tools):
        tools.failing[("git", "var")] = "fatal: unable to auto-detect email address"
        result = _init("--git")
        assert result.exit_code == 1
        assert "git config --global user.name" in result.output
        assert "git config --global user.email" in result.output
        assert not tools.ran("render")

    def test_a_render_that_fails_stops_before_git(self, tools):
        tools.failing[("render",)] = "aborted"
        result = _init("--git")
        assert result.exit_code == 1
        assert not tools.ran("git", "init")

    def test_commit_failure_says_how_to_finish(self, tools):
        tools.failing[("git", "commit")] = "pre-commit hook failed"
        result = _init("--github")
        assert result.exit_code == 1
        assert "'git commit' failed" in result.output
        assert "pre-commit hook failed" in result.output
        assert "The project itself was created" in result.output
        assert tools.project.is_dir()
        assert not tools.ran("gh", "repo", "create")

    def test_nesting_inside_another_repository_is_noted(self, tools):
        tools.outer_repo = "/home/me/coursework"
        result = _init("--git")
        assert result.exit_code == 0, result.output
        assert "is inside the git repository /home/me/coursework" in result.output
        assert tools.ran("git", "init")


class TestGitHub:
    def test_creates_private_repository_and_pushes(self, tools):
        result = _init("--github")
        assert result.exit_code == 0, result.output
        (create,) = [c for c in tools.commands("gh") if c[:3] == ["gh", "repo", "create"]]
        assert create == [
            "gh", "repo", "create", "my_data_science_project",
            "--private", "--source", ".", "--remote", "origin", "--push",
        ]
        create_cwd = tools.calls[tools.index_of("gh", "repo", "create")][1]
        assert create_cwd == tools.project
        assert "Created a private GitHub repository and pushed" in result.output
        assert "https://github.com/octo/my_data_science_project" in result.output
        # Only the address; not git's chatter about the push
        assert "set up to track" not in result.output

    def test_implies_git_and_pushes_after_the_commit(self, tools):
        _init("--github")
        assert (
            tools.index_of("render")
            < tools.index_of("git", "init")
            < tools.index_of("git", "commit")
            < tools.index_of("gh", "repo", "create")
        )

    def test_public(self, tools):
        result = _init("--github", "--public")
        assert result.exit_code == 0, result.output
        create = tools.calls[tools.index_of("gh", "repo", "create")][0]
        assert "--public" in create and "--private" not in create
        assert "Created a public GitHub repository" in result.output

    def test_explicit_private(self, tools):
        _init("--github", "--private")
        create = tools.calls[tools.index_of("gh", "repo", "create")][0]
        assert "--private" in create and "--public" not in create

    def test_uses_the_existing_gh_login(self, tools):
        _init("--github")
        assert tools.ran("gh", "auth", "status", "--hostname", "github.com")
        assert not tools.ran("gh", "auth", "login")
        assert tools.index_of("gh", "auth", "status") < tools.index_of("render")

    def test_respects_gh_host(self, tools, monkeypatch):
        monkeypatch.setenv("GH_HOST", "github.example.edu")
        _init("--github")
        assert tools.ran("gh", "auth", "status", "--hostname", "github.example.edu")

    def test_without_gh_installed_nothing_is_created(self, tools):
        tools.installed = {"git"}
        result = _init("--github")
        assert result.exit_code == 1
        assert "GitHub CLI (gh), which is not installed" in result.output
        assert "https://cli.github.com" in result.output
        assert "gh auth login" in result.output
        assert not tools.ran("render")
        assert not tools.ran("git", "init")
        assert list(tools.cwd.iterdir()) == []

    def test_without_gh_login_nothing_is_created(self, tools):
        tools.failing[("gh", "auth", "status")] = "You are not logged into any hosts"
        result = _init("--github")
        assert result.exit_code == 1
        assert "needs gh to be logged in to github.com" in result.output
        assert "Run 'gh auth login'" in result.output
        assert not tools.ran("render")
        assert not tools.ran("gh", "repo", "create")
        assert list(tools.cwd.iterdir()) == []

    def test_repo_creation_failure_keeps_the_commit_and_says_how_to_finish(self, tools):
        tools.failing[("gh", "repo", "create")] = "Name already exists on this account"
        result = _init("--github")
        assert result.exit_code == 1
        assert "Name already exists on this account" in result.output
        assert f"first commit are in {tools.project}" in result.output
        assert (
            "gh repo create my_data_science_project --private --source . "
            "--remote origin --push" in result.output
        )
        assert tools.ran("git", "commit")

    def test_scope_resolves_from_the_new_remote(self, tools):
        """After --github the remote exists, so the pipeline ID is scoped."""
        tools.project_name = "my_pipeline"
        result = _init("--github")
        assert result.exit_code == 0, result.output
        assert "Pipeline ID: octo/my_pipeline" in result.output
        # ...and that is what the first build will see
        clear_git_remote_cache()
        assert load_manifest(tools.project)["project"]["id"] == "octo/my_pipeline"

    def test_without_github_the_id_stays_bare(self, tools):
        tools.project_name = "my_pipeline"
        result = _init("--git")
        assert result.exit_code == 0, result.output
        assert "Pipeline ID" not in result.output
        assert load_manifest(tools.project)["project"]["id"] == "my_pipeline"


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture
def real_git(monkeypatch):
    """Real git, insulated from the developer's own configuration."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Test Author")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")
    clear_git_remote_cache()
    yield
    clear_git_remote_cache()


def _git(project, *args):
    return subprocess.run(
        ["git", *args], cwd=project, capture_output=True, text=True, check=True
    ).stdout


@needs_git
def test_real_git_init_and_commit(tmp_path, real_git):
    project = tmp_path / "my_pipeline"
    (project / "_data").mkdir(parents=True)
    (project / "chartbook.toml").write_text('[project]\nname = "My Pipeline"\n')
    (project / "README.md").write_text("# My Pipeline\n")
    (project / ".gitignore").write_text(".env\n_data/\n")
    (project / ".env").write_text("FRED_API_KEY=not-a-real-key\n")
    (project / "_data" / "big.parquet").write_text("data")

    scaffold.preflight(tmp_path, use_github=False)
    assert scaffold.enclosing_repository(tmp_path) is None
    scaffold.git_init_and_commit(project)

    assert _git(project, "log", "--format=%s").splitlines() == [
        "Initial commit from chartbook init"
    ]
    assert _git(project, "branch", "--show-current").strip() == "main"
    # The project's own .gitignore decides what is committed
    assert sorted(_git(project, "ls-files").split()) == [
        ".gitignore",
        "README.md",
        "chartbook.toml",
    ]
    assert _git(project, "status", "--porcelain") == ""
    assert Path(scaffold.enclosing_repository(project)).resolve() == project.resolve()


@needs_git
def test_real_remote_gives_the_pipeline_its_scope(tmp_path, real_git):
    """What `gh repo create --remote origin` leaves behind scopes the ID."""
    project = tmp_path / "my_pipeline"
    project.mkdir()
    (project / "chartbook.toml").write_text('[project]\nname = "My Pipeline"\n')
    scaffold.git_init_and_commit(project)
    assert load_manifest(project)["project"]["id"] == "my_pipeline"

    for url in (
        "https://github.com/octo/my_pipeline.git",
        "git@github.com:octo/my_pipeline.git",
    ):
        _git(project, "remote", "add", "origin", url)
        clear_git_remote_cache()
        assert load_manifest(project)["project"]["id"] == "octo/my_pipeline"
        _git(project, "remote", "remove", "origin")


REPOSITORY = Path(__file__).parent.parent


def _at_commit(monkeypatch, commit):
    """This ChartBook's template, as it is, said to be at *commit* (None: no commit known)."""
    import dataclasses

    real = scaffold.template_source
    monkeypatch.setattr(
        scaffold,
        "template_source",
        lambda package_dir=None: dataclasses.replace(
            real(package_dir), commit=commit, why="" if commit else "it was not recorded"
        ),
    )


def _template_copy(destination: Path) -> Path:
    """A copy of this repository's template at *destination*."""
    shutil.copytree(REPOSITORY / "template", destination)
    return destination


class TestTheTemplateThatCameWithIt:
    """`chartbook init` renders the template that came with this ChartBook, with no network."""

    def test_a_wheel_carries_it_in_the_package(self, tmp_path):
        """The layout `[tool.hatch.build.targets.wheel.force-include]` makes, with the commit the build recorded."""
        package = tmp_path / "site-packages" / "chartbook"
        package.mkdir(parents=True)
        _template_copy(package / "template")
        assert scaffold.find_template(package) == package / "template"
        assert scaffold.template_commit(package) is None
        (package / scaffold.BUILT_FROM).write_text(COMMIT + "\n")
        assert scaffold.template_commit(package) == COMMIT

    def test_a_source_checkout_has_it_beside_src(self, tmp_path):
        package = tmp_path / "checkout" / "src" / "chartbook"
        package.mkdir(parents=True)
        _template_copy(tmp_path / "checkout" / "template")
        assert scaffold.find_template(package) == tmp_path / "checkout" / "template"

    def test_a_copy_of_a_checkout_without_git_is_not_rendered_from(self, tmp_path):
        """With no git, which files are tracked cannot be told, and a raw `template/` may hold an ignored `.env`."""
        package = tmp_path / "copy" / "src" / "chartbook"
        package.mkdir(parents=True)
        _template_copy(tmp_path / "copy" / "template")
        with pytest.raises(scaffold.ScaffoldError, match="neither a .git nor the PKG-INFO of an sdist"):
            scaffold.render(tmp_path, no_input=True, package_dir=package)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["copy"]

    def test_an_unpacked_sdist_is_rendered_from_with_the_commit_it_carries(self, tmp_path):
        """An sdist holds the tracked files and no others, and `src/chartbook/built_from.txt`."""
        root = tmp_path / "chartbook-0.2.0"
        package = root / "src" / "chartbook"
        package.mkdir(parents=True)
        _template_copy(root / "template")
        (root / "PKG-INFO").write_text("Metadata-Version: 2.4\nName: chartbook\n")
        (package / scaffold.BUILT_FROM).write_text(COMMIT + "\n")
        assert scaffold.template_commit(package) == COMMIT
        (package / scaffold.BUILT_FROM).unlink()
        source = scaffold.template_source(package)
        assert source.commit is None and "did not record it" in source.why

    @needs_git
    def test_a_checkout_git_cannot_read_is_not_rendered_from(self, tmp_path, real_git, monkeypatch):
        """The note used to blame the build for a commit missing because git could not run."""
        package = _committed_checkout(tmp_path)
        monkeypatch.setenv("PATH", str(tmp_path / "no-git-here"))
        with pytest.raises(scaffold.ScaffoldError, match="safe.directory"):
            scaffold.template_source(package)

    def test_a_template_beside_an_installed_package_is_not_taken(self, tmp_path):
        """Only `src/` makes a folder a source checkout."""
        package = tmp_path / "lib" / "site-packages" / "chartbook"
        package.mkdir(parents=True)
        _template_copy(tmp_path / "lib" / "template")
        with pytest.raises(scaffold.ScaffoldError, match="no project template"):
            scaffold.find_template(package)

    @needs_git
    def test_a_source_checkout_is_asked_for_its_commit(self, tmp_path, real_git, monkeypatch):
        checkout = tmp_path / "checkout"
        package = checkout / "src" / "chartbook"
        package.mkdir(parents=True)
        _template_copy(checkout / "template")
        _git(checkout, "init", "--quiet")
        _git(checkout, "add", "-A")
        _git(checkout, "commit", "--quiet", "-m", "Template")
        head = _git(checkout, "rev-parse", "HEAD").strip()
        # Where the environment points git elsewhere, as inside a git hook
        monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere.git"))
        assert scaffold.template_commit(package) == head

    @needs_git
    def test_a_checkout_inside_another_repository_is_not_that_repository(self, tmp_path, real_git):
        outer = tmp_path / "outer"
        package = outer / "unpacked" / "src" / "chartbook"
        package.mkdir(parents=True)
        _template_copy(outer / "unpacked" / "template")
        (outer / "README.md").write_text("Someone else's repository\n")
        _git(outer, "init", "--quiet")
        _git(outer, "add", "README.md")
        _git(outer, "commit", "--quiet", "-m", "Theirs")
        # Neither its own checkout nor an sdist: which files are the template's cannot be told
        with pytest.raises(scaffold.ScaffoldError):
            scaffold.template_commit(package)

    def test_init_renders_it_with_no_network(self, tmp_path, monkeypatch):
        """Pressing Enter at every question: the template is read from this package, and nothing is cloned."""
        import json
        import socket

        import git

        def no_network(*args, **kwargs):
            raise AssertionError("chartbook init reached for the network")

        monkeypatch.setattr(git.Repo, "clone_from", no_network)
        monkeypatch.setattr(socket.socket, "connect", no_network)
        _at_commit(monkeypatch, COMMIT)
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(main, ["init"], input="\n" * 30)
        assert result.exit_code == 0, result.output
        project = tmp_path / "my_data_science_project"
        assert (project / "chartbook.toml").is_file()
        state = json.loads((project / ".cruft.json").read_text())
        assert state["template"] == "https://github.com/backofficedev/chartbook"
        assert state["directory"] == "template"
        assert state["commit"] == COMMIT
        # cruft create writes no `skip`; with one, cruft update adds the project's skips to it on every run
        assert state["checkout"] is None and "skip" not in state
        answers = state["context"]["cookiecutter"]
        assert answers["project_slug"] == "my_data_science_project"
        assert answers["_template"] == "https://github.com/backofficedev/chartbook" and answers["_commit"] == COMMIT
        # The floor is the ChartBook that rendered it
        from chartbook import __version__

        assert answers["_chartbook_version"] == __version__
        assert f"chartbook>={__version__}" in (project / "requirements.txt").read_text()

    @needs_git
    def test_cruft_reads_the_file_it_writes(self, tmp_path, real_git, monkeypatch):
        """`cruft check` clones the template named in `.cruft.json` and compares commits.

        Here the template is a local repository holding this one's
        `template/`, so it runs with no network; the file is otherwise as
        `chartbook init` writes it.
        """
        import json

        import cruft

        upstream = tmp_path / "upstream"
        _template_copy(upstream / "template")
        _git(upstream, "init", "--quiet")
        _git(upstream, "add", "-A")
        _git(upstream, "commit", "--quiet", "-m", "Template")
        head = _git(upstream, "rev-parse", "HEAD").strip()
        _at_commit(monkeypatch, head)
        out = tmp_path / "projects"
        out.mkdir()
        project = scaffold.render(out, no_input=True).project_dir
        cruft_file = project / ".cruft.json"
        state = json.loads(cruft_file.read_text())
        state["template"] = str(upstream)
        cruft_file.write_text(json.dumps(state))
        assert cruft.check(project) is True

    def test_with_no_commit_known_there_is_no_cruft_file(self, tmp_path, monkeypatch):
        """`"commit": null` was up to date for `cruft check`, and `cruft update` did nothing."""
        _at_commit(monkeypatch, None)
        rendered = scaffold.render(tmp_path, no_input=True)
        assert rendered.commit is None
        assert (rendered.project_dir / "chartbook.toml").is_file()
        assert not (rendered.project_dir / ".cruft.json").exists()

    def test_a_template_installed_read_only_makes_a_project_its_owner_can_write(self, tmp_path):
        """cookiecutter copies the template's modes: a Nix store or a locked tree made a read-only project."""
        import os
        import stat

        package = tmp_path / "site-packages" / "chartbook"
        package.mkdir(parents=True)
        template = _template_copy(package / "template")
        for path in [*template.rglob("*"), template]:
            path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        try:
            out = tmp_path / "projects"
            out.mkdir()
            project = scaffold.render(out, no_input=True, package_dir=package).project_dir
        finally:
            for path in [template, *template.rglob("*")]:
                path.chmod(path.stat().st_mode | stat.S_IWUSR)
        rendered = [project, *project.rglob("*")]
        assert rendered and all(os.access(path, os.W_OK) for path in rendered if not path.is_symlink())

    def test_a_refused_folder_name_prints_no_traceback(self, tmp_path):
        """The template says why, and `chartbook init` what to do; cookiecutter's log of it added a traceback.

        In a process of its own, as `chartbook init` is: pytest's own log
        handler would take the record here.
        """
        import sys

        code = (
            "import sys\n"
            "from pathlib import Path\n"
            "from cookiecutter.exceptions import FailedHookException\n"
            "from chartbook import scaffold\n"
            "try:\n"
            "    scaffold.render(Path(sys.argv[1]), no_input=True, "
            "answers={'project_name': 'Rates Study', 'project_slug': 'Rates Study'})\n"
            "except FailedHookException:\n"
            "    print('refused')\n"
        )
        result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True)
        assert "refused" in result.stdout, result.stderr
        assert "cannot be the project's folder name" in result.stdout
        assert "Traceback" not in result.stderr + result.stdout

    @needs_git
    def test_a_source_checkout_renders_only_what_git_tracks(self, tmp_path, real_git):
        """A wheel built from the checkout ships those files and no others, so a source install renders the same."""
        package = _committed_checkout(tmp_path)
        slug_folder = tmp_path / "checkout" / "template" / "{{cookiecutter.project_slug}}"
        (slug_folder / ".env").write_text("FRED_API_KEY=a-real-key-of-the-template-author\n")
        (slug_folder / ".ipynb_checkpoints").mkdir()
        (slug_folder / ".ipynb_checkpoints" / "scratch.ipynb").write_text("{}")
        # A change to a tracked file is rendered, at its content on disk
        readme = slug_folder / "README.md"
        readme.write_text(readme.read_text() + "\nAn uncommitted line.\n")
        out = tmp_path / "projects"
        out.mkdir()
        rendered = scaffold.render(out, no_input=True, package_dir=package)
        assert not (rendered.project_dir / ".env").exists()
        assert not (rendered.project_dir / ".ipynb_checkpoints").exists()
        assert "An uncommitted line." in (rendered.project_dir / "README.md").read_text()
        # ...and then the template is at no commit
        assert rendered.commit is None and not (rendered.project_dir / ".cruft.json").exists()

    @needs_git
    def test_a_template_with_uncommitted_changes_is_at_no_commit(self, tmp_path, real_git):
        package = _committed_checkout(tmp_path)
        head = scaffold.template_commit(package)
        assert head is not None
        # A file git does not track is never rendered, and does not count
        (tmp_path / "checkout" / "template" / "notes.txt").write_text("mine\n")
        assert scaffold.template_commit(package) == head
        (tmp_path / "checkout" / "template" / "cookiecutter.json").write_text("{}\n")
        assert scaffold.template_commit(package) is None
        assert "changes git has not committed" in scaffold.template_source(package).why

    @needs_git
    def test_whether_the_commit_is_on_a_remote_branch(self, tmp_path, real_git):
        """`cruft update` clones the template from GitHub: a commit only on this machine, or a fork, is not there.

        Only a remote that is the template's repository counts (a fork's
        does not), and a tag does (a `--depth 1 --branch v1` clone has only
        that).
        """
        package = _committed_checkout(tmp_path)
        checkout = tmp_path / "checkout"
        head = scaffold.template_commit(package)
        assert scaffold.commit_is_pushed(head, package) is False
        _git(checkout, "remote", "add", "fork", "https://github.com/someone/chartbook.git")
        _git(checkout, "update-ref", "refs/remotes/fork/main", head)
        assert scaffold.commit_is_pushed(head, package) is False
        _git(checkout, "tag", "v0.0.1", head)
        assert scaffold.commit_is_pushed(head, package) is True
        _git(checkout, "tag", "-d", "v0.0.1")
        _git(checkout, "remote", "add", "upstream", "git@github.com:backofficedev/chartbook.git")
        _git(checkout, "update-ref", "refs/remotes/upstream/main", head)
        assert scaffold.commit_is_pushed(head, package) is True
        # A packaged template cannot tell
        packaged = tmp_path / "site-packages" / "chartbook"
        packaged.mkdir(parents=True)
        _template_copy(packaged / "template")
        assert scaffold.commit_is_pushed(head, packaged) is None


class TestRenderingSaysWhatWentWrong:
    def test_a_folder_there_already_is_named_from_the_answer(self, tmp_path, monkeypatch):
        """Not parsed from cookiecutter's message: the folder is the output folder and the slug."""
        (tmp_path / "rates_study").mkdir()
        with pytest.raises(scaffold.ProjectExistsError) as raised:
            scaffold.render(tmp_path, no_input=True, answers={"project_name": "Rates Study"})
        assert raised.value.folder == tmp_path / "rates_study"
        assert list((tmp_path / "rates_study").iterdir()) == []

    def test_cookiecutters_log_of_a_stopped_hook_reaches_no_handler(self, tmp_path, caplog):
        """A NullHandler hid the traceback only while nothing handled the root logger; pytest's caplog does."""
        import logging

        from cookiecutter.exceptions import FailedHookException

        with caplog.at_level(logging.DEBUG):
            with pytest.raises(FailedHookException):
                scaffold.render(tmp_path, no_input=True, answers={"project_name": "Rates Study", "project_slug": "Rates Study"})
        assert not [record for record in caplog.records if record.name.startswith("cookiecutter")]
        assert logging.getLogger("cookiecutter").propagate is True

    @needs_git
    def test_a_tracked_file_missing_from_disk_stops_it(self, tmp_path, real_git):
        """A sparse checkout, or a file deleted and not committed: the template would be rendered without it."""
        package = _committed_checkout(tmp_path)
        (tmp_path / "checkout" / "template" / "hooks" / "post_gen_project.py").unlink()
        out = tmp_path / "projects"
        out.mkdir()
        with pytest.raises(scaffold.ScaffoldError, match="not on disk"):
            scaffold.render(out, no_input=True, package_dir=package)


def _committed_checkout(tmp_path: Path) -> Path:
    """A source checkout of a package with this repository's template, all committed; its package folder."""
    checkout = tmp_path / "checkout"
    package = checkout / "src" / "chartbook"
    package.mkdir(parents=True)
    _template_copy(checkout / "template")
    _git(checkout, "init", "--quiet")
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "--quiet", "-m", "Template")
    return package
