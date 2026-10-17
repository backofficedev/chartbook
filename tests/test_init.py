"""Tests for ``chartbook init --git`` / ``--github``.

``git``, ``gh`` and ``cruft`` are replaced by a fake ``subprocess.run`` that
records every command, so these tests assert on what would be run and in
what order. Two tests at the end use real git.
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

# The template is the `template/` folder of this repository
TEMPLATE = ["https://github.com/backofficedev/chartbook", "--directory", "template"]


class FakeTools:
    """Stands in for cruft, git and gh.

    ``cruft create`` renders a project directory named by ``project_name``,
    as the real one names it from the user's answers. Any command whose
    leading words are in ``failing`` returns a nonzero exit code.
    """

    def __init__(self, cwd: Path):
        self.cwd = cwd
        self.calls: list[tuple[list[str], Path]] = []
        self.installed = {"git", "gh"}
        self.failing: dict[tuple[str, ...], str] = {}
        self.project_name = "my_data_science_project"
        self.render = True
        self.remote_url = None
        # The repository the working directory is inside, if any
        self.outer_repo = None
        # The user's init.defaultBranch, if they have set one
        self.configured_branch = None

    # -- the two things the code under test calls -------------------------

    def which(self, name):
        return f"/usr/bin/{name}" if name in self.installed else None

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
        if command[0] == "cruft" and self.render:
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
    clear_git_remote_cache()
    yield fake
    clear_git_remote_cache()


def _init(*args):
    return CliRunner().invoke(main, ["init", *args])


class TestPlainInit:
    def test_runs_only_cruft(self, tools):
        result = _init()
        assert result.exit_code == 0, result.output
        assert tools.commands() == [["cruft", "create", *TEMPLATE]]
        assert scaffold.template_command() == ["cruft", "create", *TEMPLATE]

    def test_the_template_is_in_this_repository(self):
        """Where `chartbook init` says it is, there is a cookiecutter template."""
        template = Path(__file__).parent.parent / scaffold.TEMPLATE_DIRECTORY
        assert (template / "cookiecutter.json").is_file()
        assert (template / "{{cookiecutter.project_slug}}" / "chartbook.toml").is_file()

    def test_git_and_github_are_off_by_default(self, tools):
        _init()
        assert tools.commands("git") == []
        assert tools.commands("gh") == []

    @pytest.mark.parametrize("flags", [(), ("--git",)])
    def test_a_refused_folder_name_is_said_again_last(self, tools, flags):
        """The template's own message is above cruft's traceback, about 118 lines of it."""
        tools.failing[("cruft",)] = "Traceback (most recent call last): ..."
        tools.render = False
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

    def test_project_directory_is_found_not_guessed(self, tools):
        """The directory is named by an answer at cruft's prompt."""
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
        assert tools.index_of("git", "var", "GIT_AUTHOR_IDENT") < tools.index_of("cruft")

    def test_without_git_installed_nothing_is_created(self, tools):
        tools.installed = {"gh"}
        result = _init("--git")
        assert result.exit_code == 1
        assert "git is not installed" in result.output
        assert "https://git-scm.com/downloads" in result.output
        assert not tools.ran("cruft")
        assert list(tools.cwd.iterdir()) == []

    def test_without_a_git_identity_nothing_is_created(self, tools):
        tools.failing[("git", "var")] = "fatal: unable to auto-detect email address"
        result = _init("--git")
        assert result.exit_code == 1
        assert "git config --global user.name" in result.output
        assert "git config --global user.email" in result.output
        assert not tools.ran("cruft")

    def test_cruft_failure_stops_before_git(self, tools):
        tools.failing[("cruft",)] = "aborted"
        tools.render = False
        result = _init("--git")
        assert result.exit_code == 1
        assert not tools.ran("git", "init")

    def test_unidentifiable_project_is_reported(self, tools):
        tools.render = False
        result = _init("--git")
        assert result.exit_code == 1
        assert "Could not tell which directory the template was rendered into" in (
            result.output
        )
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
            tools.index_of("cruft")
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
        assert tools.index_of("gh", "auth", "status") < tools.index_of("cruft")

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
        assert not tools.ran("cruft")
        assert not tools.ran("git", "init")
        assert list(tools.cwd.iterdir()) == []

    def test_without_gh_login_nothing_is_created(self, tools):
        tools.failing[("gh", "auth", "status")] = "You are not logged into any hosts"
        result = _init("--github")
        assert result.exit_code == 1
        assert "needs gh to be logged in to github.com" in result.output
        assert "Run 'gh auth login'" in result.output
        assert not tools.ran("cruft")
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


class TestFindNewProject:
    def test_two_new_projects_is_ambiguous(self, tmp_path):
        for name in ("a", "b"):
            (tmp_path / name).mkdir()
            (tmp_path / name / ".cruft.json").write_text("{}")
        with pytest.raises(scaffold.ScaffoldError, match="a, b"):
            scaffold.find_new_project(tmp_path, before=set())

    def test_directories_without_the_marker_are_ignored(self, tmp_path):
        (tmp_path / "not_a_project").mkdir()
        (tmp_path / "project").mkdir()
        (tmp_path / "project" / ".cruft.json").write_text("{}")
        assert scaffold.find_new_project(tmp_path, before=set()) == tmp_path / "project"


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
