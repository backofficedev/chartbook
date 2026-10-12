"""Tests for what ChartBook reads from git: the repository URL and when a
pipeline's code last changed."""

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook import build_docs, manifest as manifest_module
from chartbook.build_docs import generate_docs
from chartbook.cli import main
from chartbook.identity import clear_git_remote_cache, remote_to_web_url
from chartbook.manifest import (
    apply_code_change_times,
    find_latest_code_change,
    find_latest_source_modification,
    load_manifest,
)

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

COMMIT_TIME = datetime(2025, 3, 14, 9, 26, 53)


@pytest.fixture
def git_env(monkeypatch):
    """Real git, insulated from the developer's own configuration."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Test Author")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")
    clear_git_remote_cache()
    yield
    clear_git_remote_cache()


def _git(project, *args, when=None):
    env = dict(os.environ)
    if when is not None:
        stamp = when.astimezone().isoformat()
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = stamp
    return subprocess.run(
        ["git", *args], cwd=project, env=env, capture_output=True, text=True, check=True
    ).stdout


def _commit_all(project, when=COMMIT_TIME, message="Add pipeline"):
    if not (project / ".git").exists():
        _git(project, "init")
        (project / ".gitignore").write_text("_data/\n_output/\ndocs/\n_docs*/\n")
    _git(project, "add", "--all")
    _git(project, "commit", "-m", message, when=when)


class TestRemoteToWebUrl:
    @pytest.mark.parametrize(
        "remote, expected",
        [
            ("git@github.com:acme/rates.git", "https://github.com/acme/rates"),
            ("https://github.com/acme/rates.git", "https://github.com/acme/rates"),
            ("https://github.com/acme/rates", "https://github.com/acme/rates"),
            ("ssh://git@github.com/acme/rates.git", "https://github.com/acme/rates"),
            (
                "ssh://git@gitlab.internal:2222/acme/rates.git",
                "https://gitlab.internal/acme/rates",
            ),
            ("git://example.org/acme/rates.git", "https://example.org/acme/rates"),
            (
                "gitlab.internal:group/sub/rates.git",
                "https://gitlab.internal/group/sub/rates",
            ),
            # A web port is part of the address
            ("http://gitea.local:3000/acme/rates.git", "http://gitea.local:3000/acme/rates"),
        ],
    )
    def test_remote_forms(self, remote, expected):
        assert remote_to_web_url(remote) == expected

    @pytest.mark.parametrize(
        "remote",
        [
            "https://jdoe:ghp_abc123SECRET@github.com/acme/rates.git",
            "https://x-access-token:ghs_SECRET@github.com/acme/rates",
            "https://ghp_abc123SECRET@github.com/acme/rates.git",
        ],
    )
    def test_credentials_are_never_carried_over(self, remote):
        url = remote_to_web_url(remote)
        assert url == "https://github.com/acme/rates"
        assert "SECRET" not in url and "@" not in url

    @pytest.mark.parametrize(
        "remote",
        ["/srv/git/rates.git", "../rates", "file:///srv/git/rates.git", "C:/repos/rates", "", None],
    )
    def test_a_path_on_disk_has_no_web_address(self, remote):
        assert remote_to_web_url(remote) == ""


@needs_git
class TestRepoUrlDefault:
    def test_defaults_to_the_origin_remote(self, pipeline_project, git_env):
        _commit_all(pipeline_project)
        assert load_manifest(pipeline_project)["project"]["repo_url"] == ""

        _git(pipeline_project, "remote", "add", "origin", "git@github.com:octo/rates.git")
        clear_git_remote_cache()
        assert (
            load_manifest(pipeline_project)["project"]["repo_url"]
            == "https://github.com/octo/rates"
        )

    def test_a_token_in_the_remote_does_not_reach_the_manifest(
        self, pipeline_project, git_env
    ):
        _commit_all(pipeline_project)
        _git(
            pipeline_project,
            "remote", "add", "origin",
            "https://jdoe:ghp_abc123SECRET@github.com/octo/rates.git",
        )
        clear_git_remote_cache()
        project = load_manifest(pipeline_project)["project"]
        assert project["repo_url"] == "https://github.com/octo/rates"
        assert "SECRET" not in repr(project)

    def test_explicit_repo_url_wins(self, pipeline_project, git_env):
        _commit_all(pipeline_project)
        _git(pipeline_project, "remote", "add", "origin", "git@github.com:octo/rates.git")
        toml_path = pipeline_project / "chartbook.toml"
        config = tomli.loads(toml_path.read_text())
        config["project"]["repo_url"] = "https://example.org/mirror/rates"
        toml_path.write_bytes(tomli_w.dumps(config).encode())
        clear_git_remote_cache()
        assert (
            load_manifest(pipeline_project)["project"]["repo_url"]
            == "https://example.org/mirror/rates"
        )

    def test_no_repository_means_no_url(self, pipeline_project, git_env):
        assert load_manifest(pipeline_project)["project"]["repo_url"] == ""

    def test_check_no_longer_asks_for_repo_url_once_there_is_a_remote(
        self, pipeline_project, git_env
    ):
        runner = CliRunner()
        before = runner.invoke(main, ["check", "--project-dir", str(pipeline_project)])
        assert "[project] repo_url" in before.output

        _commit_all(pipeline_project)
        _git(pipeline_project, "remote", "add", "origin", "git@github.com:octo/rates.git")
        clear_git_remote_cache()
        after = runner.invoke(main, ["check", "--project-dir", str(pipeline_project)])
        assert "[project] repo_url" not in after.output


@needs_git
class TestCodeChangeTime:
    def test_committed_code_reports_its_commit_time(self, pipeline_project, git_env):
        """Files are stamped "now" by the fixture, as a fresh clone stamps them."""
        _commit_all(pipeline_project)
        assert find_latest_code_change(pipeline_project) == COMMIT_TIME
        # ...whereas the file system says "just now"
        assert find_latest_source_modification(pipeline_project) > COMMIT_TIME

    def test_only_commits_touching_the_source_count(self, pipeline_project, git_env):
        _commit_all(pipeline_project)
        (pipeline_project / "LICENSE").write_text("MIT\n")
        _commit_all(pipeline_project, when=datetime(2026, 1, 1, 12, 0, 0), message="Add licence")
        assert find_latest_code_change(pipeline_project) == COMMIT_TIME

    def test_uncommitted_edit_falls_back_to_modification_time(
        self, pipeline_project, git_env
    ):
        _commit_all(pipeline_project)
        (pipeline_project / "src" / "dummy.py").write_text("# edited, not committed\n")
        changed = find_latest_code_change(pipeline_project)
        assert changed == find_latest_source_modification(pipeline_project)
        assert changed > COMMIT_TIME

    def test_new_untracked_source_file_counts_as_a_change(self, pipeline_project, git_env):
        _commit_all(pipeline_project)
        (pipeline_project / "src" / "new_step.py").write_text("print('new')\n")
        assert find_latest_code_change(pipeline_project) > COMMIT_TIME

    def test_changes_outside_the_source_do_not_count(self, pipeline_project, git_env):
        _commit_all(pipeline_project)
        (pipeline_project / "_data" / "test_pipeline" / "dataframe_0.parquet").touch()
        (pipeline_project / "notes.txt").write_text("scratch\n")
        assert find_latest_code_change(pipeline_project) == COMMIT_TIME

    def test_outside_a_repository_it_is_the_modification_time(self, pipeline_project, git_env):
        assert find_latest_code_change(pipeline_project) == find_latest_source_modification(
            pipeline_project
        )

    def test_without_git_it_is_the_modification_time(self, pipeline_project, monkeypatch):
        def no_git(*args, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr(manifest_module.subprocess, "run", no_git)
        assert find_latest_code_change(pipeline_project) == find_latest_source_modification(
            pipeline_project
        )


@needs_git
class TestPagesUseTheCommitTime:
    def test_built_pages_show_when_the_code_was_committed(
        self, pipeline_project, git_env, monkeypatch
    ):
        _commit_all(pipeline_project)
        monkeypatch.chdir(pipeline_project)
        generate_docs(
            output_dir=pipeline_project / "docs",
            project_dir=pipeline_project,
            keep_build_dirs=True,
        )
        page = (
            pipeline_project / "_docs" / "cb" / "dataframes" / "test_pipeline" / "dataframe_0.md"
        ).read_text()
        assert 'Code updated <time class="cb-relative-time" datetime="2025-03-14T09:26:53' in page
        assert "| Date of Last Code Update        | 2025-03-14 09:26:53" in page
        chart = (pipeline_project / "_docs" / "cb" / "charts" / "test_pipeline.chart_0_0.md").read_text()
        assert chart.startswith('---\ndate: "2025-03-14 09:26:53"')

    def test_loading_a_manifest_does_not_ask_git_about_commits(
        self, pipeline_project, git_env, monkeypatch
    ):
        """data.load() and friends must not pay for this; only a build does."""
        _commit_all(pipeline_project)
        calls = []
        real_run = manifest_module.subprocess.run

        def spy(command, **kwargs):
            calls.append(command)
            return real_run(command, **kwargs)

        monkeypatch.setattr(manifest_module.subprocess, "run", spy)
        loaded = load_manifest(pipeline_project)
        # The one-off remote lookup is the only thing git is asked
        assert not [c for c in calls if "status" in c or "log" in c]
        assert len(calls) <= 1
        assert loaded["source_last_modified_date"] != "2025-03-14 09:26:53"

    def test_apply_sets_every_pipeline_and_reuses_known_times(self, catalog_project, git_env):
        loaded = load_manifest(catalog_project)
        times = apply_code_change_times(loaded, known={"pipeline_a": "2020-01-01 00:00:00"})
        assert times["pipeline_a"] == "2020-01-01 00:00:00"
        assert loaded["pipelines"]["pipeline_a"]["source_last_modified_date"] == (
            "2020-01-01 00:00:00"
        )
        assert loaded["pipelines"]["pipeline_b"]["source_last_modified_date"] == times[
            "pipeline_b"
        ]
        assert times["pipeline_b"] != "2020-01-01 00:00:00"

    def test_incremental_build_remembers_times_for_pipelines_it_reuses(
        self, catalog_project, git_env, monkeypatch
    ):
        from chartbook.incremental import read_state

        monkeypatch.chdir(catalog_project)
        asked = []
        real = manifest_module.find_latest_code_change

        def spy(base_dir):
            asked.append(Path(base_dir).name)
            return real(base_dir)

        monkeypatch.setattr(manifest_module, "find_latest_code_change", spy)

        def build():
            return generate_docs(
                output_dir=catalog_project / "docs",
                project_dir=catalog_project,
                _docs_dir=catalog_project / "_docs",
                temp_docs_src_dir=catalog_project / "_docs_src",
                incremental=True,
            )

        build()
        assert sorted(set(asked)) == ["pipeline_a", "pipeline_b"]
        recorded = read_state(catalog_project / "_docs")["code_times"]
        assert set(recorded) == {"pipeline_a", "pipeline_b"}

        asked.clear()
        summary = build()
        assert summary.regenerated == []
        # Nothing was regenerated, so git was not asked about anything
        assert asked == []
        assert read_state(catalog_project / "_docs")["code_times"] == recorded
