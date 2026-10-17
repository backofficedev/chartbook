"""Tests for ``git`` dependencies: ``chartbook.gitcache`` and pinning from a checkout.

This is the last part of step 3 of ``docs_src/design/overview.md``. A
dependency may be a git repository: it is fetched into a cache, checked
out at one commit, and from there pinned like a directory.

Every repository here is a directory made by the test, so nothing uses the
network. The one URL that is not a path points at a port nothing listens
on, to see what an unreachable repository does.
"""

import json
import os
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jsonschema
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, data, index, lock
from chartbook.check import run_checks
from chartbook.cli import main
from chartbook.gitcache import (
    Checkout,
    GitCache,
    GitError,
    check_git_url,
    check_rev,
    default_git_cache,
    local_url,
    repository_slug,
)
from chartbook.lock import LOCK_FILE
from chartbook.manifest import load_manifest, validate_dependencies
from chartbook.store import default_store
from tests.fixtures import pin_from_snapshots

HELLO ="sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

# Nothing listens on port 1, so this fails at once and without a network
UNREACHABLE = "https://user:s3cret@localhost:1/acme/crsp.git"


def _git(directory: Path, *arguments: str) -> str:
    """Run git in a directory, as someone, and return what it printed."""
    result = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _commit(repository: Path, message: str) -> str:
    """Commit everything in a repository, and return the commit's hash."""
    _git(repository, "add", "-A")
    _git(repository, "commit", "--quiet", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _write_manifest(directory: Path, table: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table))


def _statuses(report) -> dict:
    return {
        event.asset.split(":", 1)[1]: event.status for event in report.events if event.asset
    }


def _whole(report) -> list:
    """The events that are about a whole dependency, as (status, detail)."""
    return [(event.status, event.detail) for event in report.events if event.asset is None]


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def upstream(work):
    """A pipeline in a git repository. One dataframe is committed; one is git-ignored.

    The first commit is tagged ``v1``. The branch is ``main``.
    """
    repository = work / "upstream"
    _write_manifest(
        repository,
        {
            "project": {"id": "upstream"},
            "dataframes": {
                "committed": {"path": "./data/committed.parquet", "docs": "d"},
                "ignored": {"path": "./_data/ignored.parquet", "docs": "d"},
            },
        },
    )
    (repository / "data").mkdir()
    (repository / "data" / "committed.parquet").write_bytes(b"hello")
    (repository / ".gitignore").write_text("/_data/\n")
    # What a pipeline builds and does not commit: on this disk, not in git
    (repository / "_data").mkdir()
    (repository / "_data" / "ignored.parquet").write_bytes(b"built here, never committed")
    _git(repository, "init", "--quiet", "-b", "main")
    _commit(repository, "The first version")
    _git(repository, "tag", "v1")
    return repository


def _change(upstream: Path, content: bytes = b"new numbers") -> str:
    """Commit a new version of the committed dataframe; return the commit."""
    (upstream / "data" / "committed.parquet").write_bytes(content)
    return _commit(upstream, "Newer numbers")


@pytest.fixture
def cache(work):
    return GitCache(work / "cache")


@pytest.fixture
def downstream(work, upstream):
    """A pipeline that depends on ``upstream`` by git, at its default branch."""
    directory = work / "downstream"
    _depend(directory, {"git": "../upstream"})
    return directory


def _depend(directory: Path, entry: dict, key: str = "acme/upstream") -> None:
    _write_manifest(
        directory, {"project": {"id": "downstream"}, "dependencies": {key: entry}}
    )


class TestSlug:
    @pytest.mark.parametrize(
        "url, slug",
        [
            ("https://gitlab.example.org/ftsfr/ref_data.git", "gitlab.example.org/ftsfr/ref_data"),
            ("https://gitlab.example.org/ftsfr/ref_data/", "gitlab.example.org/ftsfr/ref_data"),
            # A port stays: another port is another server
            ("https://user:token@gitlab.example.org:8443/ftsfr/ref_data.git", "gitlab.example.org_8443/ftsfr/ref_data"),
            ("git@github.com:acme/rates.git", "github.com/acme/rates"),
            ("ssh://git@github.com:2222/acme/rates", "github.com_2222/acme/rates"),
            ("https://host/group/sub/group/name.git", "host/group/sub/group/name"),
            ("/srv/git/x.git", "local/srv/git/x"),
            ("file:///srv/git/x.git", "local/srv/git/x"),
            # A component with a character that is not kept carries a hash
            # of itself, so that `a b` and `a_b` are two repositories
            ("C:\\repos\\x", "local/C_~82179da1/repos/x"),
            ("https://host/a/../../etc/b", "host/a/etc/b"),
            ("https://host/we ird/na;me", "host/we_ird~260a1c9a/na_me~f029f14e"),
        ],
    )
    def test_a_repository_gets_a_path_made_from_its_url(self, url, slug):
        assert repository_slug(url).as_posix() == slug

    def test_two_different_repositories_never_share_a_clone(self):
        pairs = [
            ("https://h/o/a b", "https://h/o/a_b"),
            ("https://h/o/r", "https://h:8443/o/r"),
            ("https://h/o/r", "ssh://git@h:2222/o/r"),
            ("/tmp/x%y", "/tmp/x_y"),
        ]
        for one, other in pairs:
            assert repository_slug(one) != repository_slug(other), (one, other)

    def test_one_repository_reached_two_ways_is_one_clone(self, cache):
        assert cache.repo_path("https://github.com/acme/rates.git") == cache.repo_path(
            "git@github.com:acme/rates"
        )

    def test_nothing_of_a_token_is_in_it(self):
        assert "token" not in str(repository_slug("https://user:token@host/a/b"))

    def test_paths_in_the_cache(self, cache, work):
        url, commit = "https://host/acme/rates.git", "a" * 40
        assert cache.repo_path(url) == work / "cache" / "repos" / "host" / "acme" / "rates.git"
        assert cache.checkout_path(url, commit) == (
            work / "cache" / "checkouts" / "host" / "acme" / "rates" / commit
        )
        with pytest.raises(ValueError, match="is not a full commit hash"):
            cache.checkout_path(url, "a1b2c3d")
        with pytest.raises(ValueError, match="is not a full commit hash"):
            cache.checkout_path(url, "../../escape")


class TestWhatGitIsHanded:
    """A URL and a revision are arguments to git. Neither may read as an option."""

    @pytest.mark.parametrize(
        "url", ["--upload-pack=touch /tmp/x", "-oProxyCommand=x", "ext::sh -c 'x'", "", "  "]
    )
    def test_a_url_git_could_misread_is_refused(self, url, cache):
        with pytest.raises(ValueError, match="is not a repository ChartBook will fetch"):
            check_git_url(url)
        with pytest.raises(ValueError):
            cache.fetch(url)
        assert not cache.root.exists()

    @pytest.mark.parametrize(
        "rev", ["--upload-pack=x", "-x", "main; rm -rf x", "a b", "main^{tree}", "@{-1}", ""]
    )
    def test_a_revision_git_could_misread_is_refused(self, rev, cache):
        with pytest.raises(ValueError, match="is not a revision ChartBook will ask git for"):
            check_rev(rev)
        with pytest.raises(ValueError):
            cache.get("/somewhere", rev)

    @pytest.mark.parametrize("rev", ["main", "v1.2", "release/2026-10", "a1b2c3d", "a" * 40, None])
    def test_a_branch_a_tag_or_a_commit_is_fine(self, rev):
        assert check_rev(rev) == rev

    def test_the_manifest_refuses_them_first(self, work):
        with pytest.raises(ValueError) as e:
            validate_dependencies({"x": {"git": "--upload-pack=x"}}, work)
        assert "[dependencies]: 'x': " in str(e.value)
        with pytest.raises(ValueError, match="is not a revision"):
            validate_dependencies({"x": {"git": "https://h/a/b", "rev": "-x"}}, work)

    def test_a_path_is_relative_to_the_manifest(self, work):
        assert local_url("../upstream", work / "downstream") == str(work / "upstream")
        assert local_url(str(work / "upstream"), work / "elsewhere") == str(work / "upstream")
        for remote in ("https://h/a/b.git", "git@h:a/b.git", "ssh://git@h/a/b", "file:///srv/x"):
            assert local_url(remote, work) == remote


class TestGitCache:
    def test_fetch_makes_a_bare_clone(self, cache, upstream):
        repo = cache.fetch(str(upstream))
        assert repo == cache.repo_path(str(upstream)) and (repo / "HEAD").is_file()
        assert not (repo / "chartbook.toml").exists()

    def test_the_url_is_not_kept_in_the_clone(self, cache, upstream):
        """So a token in a URL is never written to disk by ChartBook."""
        repo = cache.fetch(str(upstream))
        configuration = (repo / "config").read_text()
        assert "url" not in configuration and "remote" not in configuration

    def test_a_revision_becomes_a_commit(self, cache, upstream):
        first = _git(upstream, "rev-parse", "HEAD")
        second = _change(upstream)
        cache.fetch(str(upstream))
        url = str(upstream)
        assert cache.resolve(url) == second  # the default branch
        assert cache.resolve(url, "main") == second
        assert cache.resolve(url, "v1") == first
        assert cache.resolve(url, first) == first
        assert cache.resolve(url, first[:10]) == first

    def test_a_revision_the_repository_does_not_have(self, cache, upstream):
        cache.fetch(str(upstream))
        with pytest.raises(GitError, match="has no revision 'nope'"):
            cache.resolve(str(upstream), "nope")

    def test_resolving_before_fetching(self, cache, upstream):
        with pytest.raises(GitError, match="has not been fetched"):
            cache.resolve(str(upstream), "main")

    def test_checkout_writes_that_commits_files(self, cache, upstream):
        cache.fetch(str(upstream))
        commit = cache.resolve(str(upstream), "v1")
        path = cache.checkout(str(upstream), commit)
        assert path == cache.checkout_path(str(upstream), commit)
        assert (path / "data" / "committed.parquet").read_bytes() == b"hello"
        assert (path / "chartbook.toml").is_file()
        # What the repository does not commit is not in a clone of it
        assert not (path / "_data").exists()
        assert not (path / ".git").exists()

    def test_a_checkout_is_not_a_place_to_work(self, cache, upstream):
        checkout = cache.get(str(upstream))
        mode = stat.S_IMODE(os.stat(checkout.path / "data" / "committed.parquet").st_mode)
        assert mode == 0o444

    def test_a_checkout_is_made_once(self, cache, upstream):
        first = cache.get(str(upstream))
        marker = os.stat(first.path / "chartbook.toml").st_ino
        again = cache.get(str(upstream))
        assert again == first
        assert os.stat(again.path / "chartbook.toml").st_ino == marker
        assert list(first.path.parent.iterdir()) == [first.path]  # nothing left beside it

    def test_get_does_all_three(self, cache, upstream):
        commit = _git(upstream, "rev-parse", "HEAD")
        checkout = cache.get(str(upstream), "v1")
        assert checkout == Checkout(
            url=str(upstream),
            rev="v1",
            commit=commit,
            path=cache.checkout_path(str(upstream), commit),
        )

    def test_find_looks_without_running_git(self, cache, upstream, monkeypatch):
        checkout = cache.get(str(upstream))
        monkeypatch.setattr(subprocess, "run", None)  # git cannot be run at all
        assert cache.find(str(upstream), checkout.commit) == checkout.path
        assert cache.find(str(upstream), "0" * 40) is None

    def test_a_branch_moves_and_a_tag_does_not(self, cache, upstream):
        first = cache.get(str(upstream), "main").commit
        second = _change(upstream)
        # Without fetching, the clone is as it was
        assert cache.get(str(upstream), "main", fetch=False).commit == first
        assert cache.get(str(upstream), "main").commit == second
        assert cache.get(str(upstream), "v1").commit == first
        assert cache.get(str(upstream)).commit == second

    def test_a_commit_that_no_branch_leads_to_is_asked_for_by_name(self, cache, upstream):
        """Fetching branches and tags does not bring it; asking for it does."""
        orphan = _change(upstream)
        _git(upstream, "reset", "--quiet", "--hard", "v1")
        cache.fetch(str(upstream))
        with pytest.raises(GitError, match="has no revision"):
            cache.resolve(str(upstream), orphan)

        checkout = cache.get(str(upstream), orphan)
        assert checkout.commit == orphan
        assert (checkout.path / "data" / "committed.parquet").read_bytes() == b"new numbers"

    def test_a_commit_that_does_not_exist(self, cache, upstream):
        with pytest.raises(GitError):
            cache.get(str(upstream), "0123456789abcdef0123456789abcdef01234567")

    def test_a_repository_that_is_not_there(self, cache, work):
        with pytest.raises(GitError):
            cache.fetch(str(work / "no_such_repository"))

    def test_a_message_never_shows_a_urls_credentials(self, cache):
        with pytest.raises(GitError) as e:
            cache.fetch(UNREACHABLE)
        assert "s3cret" not in str(e.value)

    def test_without_git_it_says_so(self, cache, upstream, monkeypatch):
        def no_git(*args, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr(subprocess, "run", no_git)
        with pytest.raises(GitError, match="git is not installed"):
            cache.fetch(str(upstream))

    def test_two_checkouts_at_once_make_one(self, cache, upstream):
        cache.fetch(str(upstream))
        commit = cache.resolve(str(upstream))
        with ThreadPoolExecutor(max_workers=6) as pool:
            paths = set(pool.map(lambda _: cache.checkout(str(upstream), commit), range(12)))
        assert paths == {cache.checkout_path(str(upstream), commit)}
        assert [p.name for p in paths.pop().parent.iterdir()] == [commit]


class TestWhereTheCacheIs:
    @pytest.fixture
    def fake_config_dir(self, work, monkeypatch):
        fake_dir = work / ".chartbook"
        monkeypatch.setattr(config, "get_global_config_dir", lambda: fake_dir)
        monkeypatch.setattr(
            config, "get_global_settings_path", lambda: fake_dir / "settings.toml"
        )
        monkeypatch.delenv(config.GIT_CACHE_ENV_VAR, raising=False)
        return fake_dir

    def test_beside_the_store_by_default(self, fake_config_dir):
        assert config.get_git_cache_path() == fake_config_dir / "git"
        assert default_git_cache().root == fake_config_dir / "git"

    def test_the_settings_file_can_move_it(self, fake_config_dir, work):
        fake_config_dir.mkdir()
        (fake_config_dir / "settings.toml").write_text(
            tomli_w.dumps({"git": {"path": str(work / "big")}})
        )
        assert config.get_git_cache_path() == work / "big"

    def test_the_environment_wins(self, fake_config_dir, work, monkeypatch):
        fake_config_dir.mkdir()
        (fake_config_dir / "settings.toml").write_text(
            tomli_w.dumps({"git": {"path": str(work / "big")}})
        )
        monkeypatch.setenv(config.GIT_CACHE_ENV_VAR, str(work / "shared"))
        assert config.get_git_cache_path() == work / "shared"

    def test_a_git_table_without_a_path_is_an_error(self, fake_config_dir):
        fake_config_dir.mkdir()
        (fake_config_dir / "settings.toml").write_text(tomli_w.dumps({"git": {"dir": "/x"}}))
        with pytest.raises(ValueError, match=r"\[git\] needs a 'path'"):
            config.get_git_cache_path()

    def test_every_test_gets_a_scratch_one(self):
        """The safeguard in conftest.py: never the real ~/.chartbook."""
        assert Path.home() / ".chartbook" not in default_git_cache().root.parents
        assert Path.home() / ".chartbook" not in default_store().root.parents


class TestPinning:
    def test_a_git_dependency_is_fetched_and_pinned_from_its_checkout(
        self, downstream, upstream, cache
    ):
        commit = _git(upstream, "rev-parse", "HEAD")
        report = lock.pin(downstream, git_cache=cache)
        assert _whole(report) == [("fetched", f"../upstream at {commit[:7]}")]
        assert _statuses(report) == {"committed": "pinned", "ignored": "not_built"}
        assert report.git == {"acme/upstream"} and report.problems == []

        locked = lock.read_lock(downstream)
        assert locked.dependencies == [
            {
                "id": "acme/upstream",
                "via": "rev",
                "location": {"kind": "git", "url": "../upstream", "commit": commit},
                "pinned_hash": locked.dependencies[0]["pinned_hash"],
            }
        ]
        assert locked.assets["acme/upstream:committed"]["content_hash"] == HELLO
        assert "content_hash" not in locked.assets["acme/upstream:ignored"]

    def test_only_what_the_repository_commits_can_be_pinned(self, downstream, upstream, cache):
        """The file is on the upstream's own disk. It is not in a clone."""
        assert (upstream / "_data" / "ignored.parquet").is_file()
        report = lock.pin(downstream, git_cache=cache)
        (event,) = [e for e in report.events if e.status == "not_built"]
        assert event.asset == "acme/upstream:ignored"

    def test_its_assets_are_read_like_any_others(self, downstream, cache):
        lock.pin(downstream, git_cache=cache)
        path = data.path("upstream:committed", project_dir=downstream)
        assert path == default_store().get(HELLO) / "committed.parquet"
        assert path.read_bytes() == b"hello"

    def test_the_lockfile_has_no_absolute_path_and_no_token(self, downstream, cache, work):
        lock.pin(downstream, git_cache=cache)
        text = (downstream / LOCK_FILE).read_text()
        assert str(work) not in text
        assert json.loads(text)["records"][0]["dependencies"][0]["location"]["url"] == "../upstream"

    def test_pinning_again_does_not_use_the_network(self, downstream, cache, monkeypatch):
        lock.pin(downstream, git_cache=cache)
        before = (downstream / LOCK_FILE).read_bytes()

        def offline(url):
            raise GitError("the network is down")

        monkeypatch.setattr(cache, "fetch", offline)
        report = lock.pin(downstream, git_cache=cache)
        assert _whole(report) == [] and report.problems == []
        assert _statuses(report) == {"committed": "kept", "ignored": "not_built"}
        assert (downstream / LOCK_FILE).read_bytes() == before

    def test_pin_stays_at_the_commit_it_pinned(self, downstream, upstream, cache):
        """The branch moves on. `pin` never moves a pin."""
        lock.pin(downstream, git_cache=cache)
        before = (downstream / LOCK_FILE).read_bytes()
        _change(upstream)

        report = lock.pin(downstream, git_cache=cache)
        assert _statuses(report)["committed"] == "kept"
        assert (downstream / LOCK_FILE).read_bytes() == before
        assert data.path("upstream:committed", project_dir=downstream).read_bytes() == b"hello"

    def test_update_asks_the_repository_what_the_branch_means_now(
        self, downstream, upstream, cache
    ):
        lock.pin(downstream, git_cache=cache)
        first = lock.read_lock(downstream).dependencies[0]["location"]["commit"]
        second = _change(upstream)

        report = lock.update(downstream, git_cache=cache)
        assert _whole(report) == [("fetched", f"../upstream at {second[:7]}")]
        assert _statuses(report)["committed"] == "moved"
        assert lock.read_lock(downstream).dependencies[0]["location"]["commit"] == second
        assert second != first
        assert data.path("upstream:committed", project_dir=downstream).read_bytes() == (
            b"new numbers"
        )

    def test_a_tag_does_not_move_on_update(self, downstream, upstream, cache):
        _depend(downstream, {"git": "../upstream", "rev": "v1"})
        report = lock.pin(downstream, git_cache=cache)
        first = _git(upstream, "rev-parse", "v1")
        assert _whole(report) == [("fetched", f"../upstream at {first[:7]} (v1)")]
        assert lock.read_lock(downstream).dependencies[0]["location"] == {
            "kind": "git",
            "url": "../upstream",
            "rev": "v1",
            "commit": first,
        }
        _change(upstream)
        report = lock.update(downstream, git_cache=cache)
        assert _statuses(report)["committed"] == "kept"
        assert lock.read_lock(downstream).dependencies[0]["location"]["commit"] == first

    def test_a_changed_rev_is_followed_by_update_not_by_pin(self, downstream, upstream, cache):
        _depend(downstream, {"git": "../upstream", "rev": "v1"})
        lock.pin(downstream, git_cache=cache)
        before = (downstream / LOCK_FILE).read_bytes()
        second = _change(upstream)

        _depend(downstream, {"git": "../upstream", "rev": "main"})
        report = lock.pin(downstream, git_cache=cache)
        assert _whole(report) == [("relocated", "../upstream at main")]
        assert (downstream / LOCK_FILE).read_bytes() == before

        report = lock.update(downstream, ["upstream"], git_cache=cache)
        assert lock.read_lock(downstream).dependencies[0]["location"] == {
            "kind": "git",
            "url": "../upstream",
            "rev": "main",
            "commit": second,
        }
        assert _statuses(report)["committed"] == "moved"

    def test_a_checkout_this_disk_has_lost_is_fetched_again(self, downstream, cache, work):
        lock.pin(downstream, git_cache=cache)
        commit = lock.read_lock(downstream).dependencies[0]["location"]["commit"]
        fresh = GitCache(work / "another_machine")
        report = lock.pin(downstream, git_cache=fresh)
        assert _whole(report) == [("fetched", f"../upstream at {commit[:7]}")]
        assert fresh.find(str(work / "upstream"), commit) is not None

    def test_a_repository_that_cannot_be_reached(self, downstream, cache):
        _depend(downstream, {"git": UNREACHABLE}, key="crsp")
        report = lock.pin(downstream, git_cache=cache)
        (problem,) = report.problems
        assert problem.status == "unfetched" and problem.dependency == "crsp"
        assert problem.detail.startswith("could not fetch https://localhost:1/acme/crsp.git: ")
        assert "s3cret" not in problem.detail
        text = (downstream / LOCK_FILE).read_text()
        assert "s3cret" not in text
        assert lock.read_lock(downstream).dependencies == [
            {
                "id": "crsp",
                "via": "rev",
                "location": {"kind": "git", "url": "https://localhost:1/acme/crsp.git"},
            }
        ]

    def test_a_pinned_repository_can_go_away(self, downstream, upstream, cache, work):
        """Its pins are in the store, as with a directory that has gone."""
        lock.pin(downstream, git_cache=cache)
        before = (downstream / LOCK_FILE).read_bytes()
        os.rename(upstream, work / "moved_away")

        report = lock.pin(downstream, git_cache=GitCache(work / "another_machine"))
        assert report.problems == []
        assert _statuses(report) == {"committed": "kept"}
        assert (downstream / LOCK_FILE).read_bytes() == before
        assert data.path("upstream:committed", project_dir=downstream).read_bytes() == b"hello"

        # ...but an update needs it
        report = lock.update(downstream, git_cache=GitCache(work / "another_machine"))
        assert [p.status for p in report.problems] == ["unfetched"]
        assert (downstream / LOCK_FILE).read_bytes() == before

    def test_beside_a_path_dependency(self, downstream, upstream, cache, work):
        _write_manifest(work / "local", {"dataframes": {"x": {"path": "./x.parquet", "docs": "d"}}})
        (work / "local" / "x.parquet").write_bytes(b"x")
        _write_manifest(
            downstream,
            {
                "dependencies": {
                    "acme/upstream": {"git": "../upstream"},
                    "local": {"path": "../local"},
                }
            },
        )
        report = pin_from_snapshots(downstream, git_cache=cache)
        assert report.git == {"acme/upstream"}
        assert set(report.snapshots) == {"local"}
        assert set(lock.read_lock(downstream).assets) == {
            "acme/upstream:committed",
            "acme/upstream:ignored",
            "local:x",
        }


class TestCheck:
    def _add_model(self, directory: Path, trained_on: list) -> None:
        (directory / "_models").mkdir(exist_ok=True)
        (directory / "_models" / "m.json").write_text("{}")
        with open(directory / "chartbook.toml", "a") as f:
            table = {"models": {"m": {"path": "./_models/m.json", "trained_on": trained_on}}}
            f.write("\n" + tomli_w.dumps(table))

    def test_before_it_is_fetched_check_says_so_and_does_not_fetch(
        self, downstream, monkeypatch
    ):
        def never(self, *arguments, **keywords):
            raise AssertionError(f"a check ran git {arguments}")

        monkeypatch.setattr(GitCache, "_git", never)
        with pytest.warns(UserWarning, match="has not been fetched here"):
            problems = run_checks(load_manifest(downstream), downstream)
        assert not [p for p in problems if p.table.startswith("dependencies")]

    def test_once_fetched_check_still_does_not_run_git(self, downstream, monkeypatch):
        lock.pin(downstream)

        def never(self, *arguments, **keywords):
            raise AssertionError(f"a check ran git {arguments}")

        monkeypatch.setattr(GitCache, "_git", never)
        problems = run_checks(load_manifest(downstream), downstream)
        assert not [p for p in problems if p.table.startswith("dependencies")]

    def test_once_fetched_training_data_is_checked_against_it(self, downstream, recwarn):
        self._add_model(downstream, ["upstream:committed", "upstream:no_such_table"])
        lock.pin(downstream)  # into this test's own cache and store
        problems = run_checks(load_manifest(downstream), downstream)
        (problem,) = [p for p in problems if p.field == "trained_on"]
        assert "'upstream:no_such_table' names a dataframe that the pipeline" in problem.message
        assert "Its dataframes are: committed, ignored" in problem.message
        assert not [w for w in recwarn if "has not been fetched" in str(w.message)]

    def test_a_repository_that_holds_no_pipeline(self, downstream, upstream):
        (upstream / "chartbook.toml").unlink()
        _commit(upstream, "No longer a pipeline")
        lock.pin(downstream)
        (problem,) = [
            p
            for p in run_checks(load_manifest(downstream), downstream)
            if p.table.startswith("dependencies")
        ]
        assert problem.table == 'dependencies."acme/upstream"' and problem.field == "git"
        assert "no chartbook.toml in" in problem.message


class TestInTheIndex:
    def test_a_dependency_names_the_commit_it_is_pinned_at(self, downstream, upstream):
        _depend(downstream, {"git": "../upstream", "rev": "main"})
        before = index.build_index(load_manifest(downstream))
        (dependency,) = before["records"][0]["dependencies"]
        assert dependency["location"] == {"kind": "git", "url": "../upstream", "rev": "main"}

        lock.pin(downstream)
        commit = _git(upstream, "rev-parse", "HEAD")
        built = index.build_index(load_manifest(downstream))
        (dependency,) = built["records"][0]["dependencies"]
        assert dependency["location"] == {
            "kind": "git",
            "url": "../upstream",
            "rev": "main",
            "commit": commit,
        }
        assert dependency["via"] == "rev" and dependency["pinned_hash"].startswith("sha256:")
        schema = json.loads(index.schema_path("Pipeline").read_text())
        jsonschema.validate(built["records"][0], schema)

    def test_the_schema_wants_a_whole_commit(self):
        schema = json.loads(index.schema_path("Pipeline").read_text())
        record = {
            "kind": "Pipeline",
            "version": "chartbook/v1",
            "id": "p",
            "name": "P",
            "location": {"kind": "path"},
            "assets": [],
            "dependencies": [
                {
                    "id": "x",
                    "via": "rev",
                    "location": {"kind": "git", "url": "https://h/a/b", "commit": "a1b2c3d"},
                }
            ],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(record, schema)


class TestCommands:
    def _run(self, *arguments):
        return CliRunner().invoke(main, list(arguments))

    def test_pin_says_what_it_fetched_and_what_a_clone_lacks(
        self, downstream, upstream, monkeypatch
    ):
        monkeypatch.chdir(downstream)
        commit = _git(upstream, "rev-parse", "HEAD")
        result = self._run("pin")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [
            f"acme/upstream: fetched ../upstream at {commit[:7]}",
            "acme/upstream: 1 pinned, 1 not built",
            "  not built: acme/upstream:ignored (./_data/ignored.parquet)",
            "  A git dependency has only what its repository commits.",
            "Wrote chartbook.lock.",
        ]

    def test_update_follows_the_branch(self, downstream, upstream, monkeypatch):
        monkeypatch.chdir(downstream)
        self._run("pin")
        second = _change(upstream)
        result = self._run("update")
        assert result.exit_code == 0, result.output
        assert f"acme/upstream: fetched ../upstream at {second[:7]}" in result.output
        assert "acme/upstream: 1 moved, 1 not built" in result.output

    def test_a_changed_rev_is_pointed_out(self, downstream, upstream, monkeypatch):
        monkeypatch.chdir(downstream)
        _depend(downstream, {"git": "../upstream", "rev": "v1"})
        self._run("pin")
        _depend(downstream, {"git": "../upstream", "rev": "main"})
        result = self._run("pin")
        assert result.exit_code == 0, result.output
        assert (
            "  [dependencies] now says ../upstream at main. It stays pinned where "
            "it was: `chartbook update acme/upstream` follows it."
        ) in result.output

    def test_a_repository_that_cannot_be_reached_fails_without_its_token(
        self, downstream, monkeypatch
    ):
        monkeypatch.chdir(downstream)
        _depend(downstream, {"git": UNREACHABLE}, key="crsp")
        result = self._run("pin")
        assert result.exit_code == 1
        assert "crsp: cannot be pinned: could not fetch https://localhost:1/acme/crsp.git" in (
            result.output
        )
        assert "s3cret" not in result.output

    def test_path_prints_the_pinned_copy(self, downstream, monkeypatch):
        monkeypatch.chdir(downstream)
        self._run("pin")
        result = self._run("path", "upstream:committed")
        assert result.exit_code == 0, result.output
        assert result.stdout.strip() == str(default_store().get(HELLO) / "committed.parquet")
