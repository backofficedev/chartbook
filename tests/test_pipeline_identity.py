"""A pipeline's ID is its repository's, whatever its folder is called; and when an ID changes, what
depended on the old one is told."""

from pathlib import Path

import pytest
import tomli
import tomli_w

from chartbook.identity import clear_git_remote_cache, derive_pipeline_id
from tests.fixtures import _git


@pytest.fixture(autouse=True)
def _fresh_git_lookups():
    clear_git_remote_cache()
    yield
    clear_git_remote_cache()


def _repository(folder: Path, remote: str = "") -> Path:
    """A git repository with one commit of an empty chartbook.toml, and an origin remote if given."""
    folder.mkdir(parents=True, exist_ok=True)
    if not (folder / "chartbook.toml").exists():
        (folder / "chartbook.toml").write_text("", encoding="utf-8")
    _git(folder, "init", "--quiet", "-b", "main")
    if remote:
        _git(folder, "remote", "add", "origin", remote)
    _git(folder, "add", "-A")
    _git(folder, "commit", "--quiet", "-m", "Start")
    return folder


class TestTheRule:
    def test_a_clone_in_a_folder_of_another_name_is_named_as_its_repository(self, tmp_path):
        """Found by a new-user test: a clone into `first-copy` was `testorg/first_copy`."""
        folder = _repository(tmp_path / "first-copy", "https://github.com/testorg/first_pipeline")
        assert derive_pipeline_id({}, folder) == "testorg/first_pipeline"

    def test_a_git_worktree_is_named_as_its_repository(self, tmp_path):
        main = _repository(tmp_path / "first_pipeline", "git@github.com:testorg/first_pipeline.git")
        _git(main, "worktree", "add", "--quiet", str(tmp_path / "agent-7f3a"), "-b", "work")
        assert derive_pipeline_id({}, tmp_path / "agent-7f3a") == "testorg/first_pipeline"
        assert derive_pipeline_id({}, main) == "testorg/first_pipeline"

    def test_a_pipeline_in_a_subfolder_keeps_the_subfolders_name(self, tmp_path):
        top = tmp_path / "monorepo"
        (top / "yield-curve").mkdir(parents=True)
        (top / "yield-curve" / "chartbook.toml").write_text("", encoding="utf-8")
        _repository(top, "https://github.com/acme/monorepo")
        assert derive_pipeline_id({}, top / "yield-curve") == "acme/yield_curve"

    def test_with_no_remote_the_folders_name(self, tmp_path):
        folder = _repository(tmp_path / "first-copy")
        assert derive_pipeline_id({}, folder) == "first_copy"

    def test_an_explicit_id_wins(self, tmp_path):
        folder = _repository(tmp_path / "first-copy", "https://github.com/testorg/first_pipeline")
        assert derive_pipeline_id({"id": "acme/rates"}, folder) == "acme/rates"

    def test_a_repository_name_is_written_as_a_folders_is(self, tmp_path):
        """`crsp-treasury` cloned into a folder of its own name keeps the ID it always had."""
        folder = _repository(tmp_path / "crsp-treasury", "https://github.com/ftsfr/CRSP-Treasury.git")
        assert derive_pipeline_id({}, folder) == "ftsfr/crsp_treasury"
        other = _repository(tmp_path / "elsewhere", "https://github.com/ftsfr/crsp-treasury.git")
        assert derive_pipeline_id({}, other) == "ftsfr/crsp_treasury"

    def test_repo_url_names_it_as_the_remote_would(self, tmp_path):
        folder = _repository(tmp_path / "checkout")
        assert derive_pipeline_id({"repo_url": "https://github.com/acme/rates"}, folder) == "acme/rates"
        # Outside any repository, the folder is all there is to go by
        loose = tmp_path / "loose" / "rates_copy"
        loose.mkdir(parents=True)
        assert derive_pipeline_id({"repo_url": "https://github.com/acme/rates"}, loose) == "acme/rates_copy"

    @pytest.mark.parametrize(
        "remote",
        [
            "https://github.com/Acme/Rates",
            "org-123@github.com:acme/rates.git",
            "github.com:acme/rates.git",
            "ssh://git@github.com:22/ACME/rates.git",
            "https://user:token@github.com/acme/rates/",
        ],
    )
    def test_every_way_of_writing_one_remote_gives_one_id(self, tmp_path, remote):
        """Found by a review: an SCP remote with another user, or none, gave the folder's name, and a
        capital in the scope gave another ID on a machine whose remote was written otherwise."""
        folder = _repository(tmp_path / "copy", remote)
        assert derive_pipeline_id({}, folder) == "acme/rates"

    @pytest.mark.parametrize("repository", ["_.._", "-.-", "..."])
    def test_a_name_of_dots_is_no_name(self, tmp_path, repository):
        """Found by a review: a repository named `_.._` gave the invalid ID `acme/..`."""
        from chartbook.identity import validate_pipeline_id

        folder = _repository(tmp_path / "rates", f"https://github.com/acme/{repository}")
        assert validate_pipeline_id(derive_pipeline_id({}, folder)) == "acme/rates"
        loose = tmp_path / "_._"
        loose.mkdir()
        assert derive_pipeline_id({}, loose) == "pipeline"

    def test_a_git_dir_in_the_environment_does_not_say_where_a_folder_is(self, tmp_path, monkeypatch):
        """Found by a review: with GIT_DIR exported, as in a git hook, a subfolder was taken for the
        repository's top, and its pipeline named after the repository."""
        top = tmp_path / "monorepo"
        (top / "rates").mkdir(parents=True)
        (top / "rates" / "chartbook.toml").write_text("", encoding="utf-8")
        _repository(top, "https://github.com/acme/monorepo")
        monkeypatch.setenv("GIT_DIR", str(top / ".git"))
        assert derive_pipeline_id({}, top / "rates") == "acme/rates"

    def test_an_address_matches_the_id_it_derives(self):
        """Found by a review: the address of `ftsfr/crsp_treasury`'s repository did not find it."""
        from chartbook.identity import match_pipeline_ref

        keys = ["ftsfr/crsp_treasury", "acme/rates"]
        assert match_pipeline_ref(keys, "https://github.com/ftsfr/crsp-treasury") == "ftsfr/crsp_treasury"
        assert match_pipeline_ref(keys, "git@github.com:Acme/Rates.git") == "acme/rates"
        # An ID written with a `-` is still found by its address as written
        assert match_pipeline_ref(["ftsfr/crsp-treasury"], "https://github.com/ftsfr/crsp-treasury") == "ftsfr/crsp-treasury"

    def test_a_snapshot_at_the_same_commit_under_a_new_id_is_made(self, tmp_path):
        """A record of the commit made under the old ID is not this pipeline's: a new one is made."""
        from chartbook import snapshot

        folder = _pipeline_with_data(tmp_path / "first-copy")
        assert snapshot.make(folder).snapshot.pipeline == "first_copy"
        moved = folder.rename(tmp_path / "first_pipeline")
        clear_git_remote_cache()
        report = snapshot.make(moved)
        assert report.made and report.snapshot.pipeline == "first_pipeline"
        assert snapshot.make(moved).made is False  # and that one is reused, as any is

    def test_the_manifest_and_the_snapshot_agree(self, tmp_path):
        from chartbook import snapshot
        from chartbook.manifest import load_manifest

        folder = _repository(tmp_path / "first-copy", "https://github.com/testorg/first_pipeline")
        assert load_manifest(folder)["project"]["id"] == "testorg/first_pipeline"
        assert snapshot.pipeline_in(folder) == "testorg/first_pipeline"


def _pipeline_with_data(folder: Path, value: float = 1.0) -> Path:
    """A pipeline in its own repository, with no remote: one dataframe, built and git-ignored."""
    import polars as pl

    folder.mkdir(parents=True, exist_ok=True)
    (folder / "chartbook.toml").write_text(
        '[dataframes.rates]\nname = "Rates"\npath = "_data/rates.parquet"\ndocs = "Rates."\n', encoding="utf-8"
    )
    (folder / ".gitignore").write_text("_data/\nchartbook.lock\n", encoding="utf-8")
    (folder / "_data").mkdir(exist_ok=True)
    pl.DataFrame({"value": [value]}).write_parquet(folder / "_data" / "rates.parquet")
    if not (folder / ".git").exists():
        _git(folder, "init", "--quiet", "-b", "main")
    _git(folder, "add", "-A")
    _git(folder, "commit", "--quiet", "--allow-empty", "-m", "Work")
    return folder


def _depending_on(folder: Path, key: str, entry: str = "{}") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "chartbook.toml").write_text(f'[dependencies]\n"{key}" = {entry}\n', encoding="utf-8")
    return folder


@pytest.fixture
def renamed(tmp_path):
    """`second` depends on `first_pipeline` by its ID, pinned; then `first_pipeline` gets a remote, so its
    ID is `testorg/first_pipeline`, and a snapshot is made under that."""
    from chartbook import lock, snapshot

    first = _pipeline_with_data(tmp_path / "first_pipeline")
    old = snapshot.make(first).snapshot
    assert old.pipeline == "first_pipeline"
    second = _depending_on(tmp_path / "second", "first_pipeline")
    assert lock.pin(second).count("pinned") == 1
    _git(first, "remote", "add", "origin", "https://github.com/testorg/first_pipeline")
    clear_git_remote_cache()
    _pipeline_with_data(first, value=2.0)
    new = snapshot.make(first).snapshot
    assert new.pipeline == "testorg/first_pipeline"
    return first, second, old, new


class TestPinSaysTheIdChanged:
    def test_update_says_so_and_names_the_entry(self, renamed):
        """Found by a new-user test: `first_pipeline: 1 already pinned`, forever, with no hint."""
        from chartbook import lock

        first, second, old, new = renamed
        report = lock.update(second)
        (event,) = [e for e in report.events if e.status == "id_changed"]
        assert "testorg/first_pipeline" in event.detail
        assert '"first_pipeline" = { id = "testorg/first_pipeline" }' in event.detail
        assert "`chartbook update first_pipeline`" in event.detail
        assert not report.problems and report.count("kept") == 1

    def test_pin_says_so_too(self, renamed):
        from chartbook import lock

        first, second, old, new = renamed
        assert lock.pin(second).count("id_changed") == 1

    def test_the_command_prints_it(self, renamed):
        from click.testing import CliRunner

        from chartbook.cli import main

        first, second, old, new = renamed
        result = CliRunner().invoke(main, ["update", "--project-dir", str(second)])
        assert result.exit_code == 0, result.output
        assert "first_pipeline: 1 already pinned" in result.output
        assert 'write "first_pipeline" = { id = "testorg/first_pipeline" } under [dependencies]' in result.output

    def test_the_entry_it_names_follows_the_pipeline(self, renamed):
        from chartbook import lock

        first, second, old, new = renamed
        _depending_on(second, "first_pipeline", '{ id = "testorg/first_pipeline" }')
        report = lock.update(second, ["first_pipeline"])
        assert report.count("moved") == 1 and report.count("id_changed") == 0
        assert report.snapshots["first_pipeline"].pipeline == "testorg/first_pipeline"

    def test_nothing_is_said_while_the_id_has_the_newest(self, renamed):
        from chartbook import lock, snapshot

        first, second, old, new = renamed
        # The remote taken away again: the old ID makes the newest snapshot
        _git(first, "remote", "remove", "origin")
        clear_git_remote_cache()
        _pipeline_with_data(first, value=3.0)
        assert snapshot.make(first).snapshot.pipeline == "first_pipeline"
        report = lock.update(second)
        assert report.count("id_changed") == 0 and report.count("moved") == 1

    def test_another_pipeline_of_the_same_repository_is_not_taken_for_it(self, tmp_path):
        """Two pipelines in one repository's subfolders share its address and first commit."""
        from chartbook import lock, snapshot

        top = tmp_path / "monorepo"
        for name in ("rates", "curve"):
            folder = top / name
            folder.mkdir(parents=True)
            (folder / "chartbook.toml").write_text('[dataframes.x]\npath = "x.csv"\n', encoding="utf-8")
            (folder / "x.csv").write_text("a\n1\n", encoding="utf-8")
        _repository(top, "https://github.com/acme/monorepo")
        snapshot.make(top / "rates")
        second = _depending_on(tmp_path / "second", "acme/rates")
        assert lock.pin(second).count("pinned") == 1
        snapshot.make(top / "curve")
        assert lock.update(second).count("id_changed") == 0


def _check(folder: Path) -> str:
    from click.testing import CliRunner

    from chartbook.cli import main

    return CliRunner().invoke(main, ["check", "--project-dir", str(folder), "--skip-outputs"]).output


class TestCheckSaysTheIdChanged:
    def test_a_dependency_whose_folder_calls_itself_something_else_now(self, renamed):
        first, second, old, new = renamed
        output = _check(second)
        assert f"first_pipeline is the pipeline in {first}, which calls itself testorg/first_pipeline now" in output
        assert 'Write "first_pipeline" = { id = "testorg/first_pipeline" } to follow it' in output

    def test_not_once_it_follows_it(self, renamed):
        first, second, old, new = renamed
        _depending_on(second, "first_pipeline", '{ id = "testorg/first_pipeline" }')
        assert "calls itself" not in _check(second)

    def test_a_catalog_key_its_folder_no_longer_gives_itself(self, renamed, tmp_path):
        """Found by a new-user test: the entry `catalog add` wrote showed only the old ID's versions."""
        first, second, old, new = renamed
        catalog = tmp_path / "catalog"
        catalog.mkdir()
        (catalog / "chartbook.toml").write_text(
            '[project]\ntype = "catalog"\n\n[pipelines.first_pipeline]\npath = "../first_pipeline"\n\n'
            '[pipelines.second]\npath = "../second"\n', encoding="utf-8"
        )
        output = _check(catalog)
        assert '[pipelines.first_pipeline] the pipeline in' in output
        assert "calls itself testorg/first_pipeline now" in output
        assert 'Name the entry "testorg/first_pipeline" to show them' in output
        # And the dependency on it, by the catalog's own folder of it
        assert 'Write "first_pipeline" = { id = "testorg/first_pipeline" }' in output
        assert "pipelines.second" not in output


def _catalog(folder: Path, pipelines: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "chartbook.toml").write_text(f'[project]\ntype = "catalog"\n\n{pipelines}', encoding="utf-8")
    return folder


@pytest.fixture
def two_checkouts(tmp_path):
    """`repos/first_pipeline`, a repository with a remote, and a second worktree of it, `repos/first-feature`."""
    from tests.fixtures import _git as run

    main = _repository(tmp_path / "repos" / "first_pipeline", "https://github.com/testorg/first_pipeline")
    run(main, "worktree", "add", "--quiet", str(tmp_path / "repos" / "first-feature"), "-b", "feature")
    return tmp_path, main, tmp_path / "repos" / "first-feature"


class TestTwoCheckoutsOfOneRepository:
    """Found by a review: under the new rule two checkouts of one repository derive one ID, and a
    `members` glob covering both made the whole catalog fail to load."""

    def test_members_show_the_main_worktree_once(self, two_checkouts):
        from chartbook.manifest import load_manifest

        root, main, feature = two_checkouts
        catalog = _catalog(root / "catalog", '[pipelines]\nmembers = ["../repos/*"]\n')
        with pytest.warns(UserWarning, match="are checkouts of one repository") as said:
            loaded = load_manifest(catalog)
        assert list(loaded["pipelines"]) == ["testorg/first_pipeline"]
        assert Path(loaded["pipelines"]["testorg/first_pipeline"]["pipeline_base_dir"]) == main.resolve()
        assert str(feature.resolve()) in str(said[0].message)

    def test_two_clones_show_the_one_found_first(self, two_checkouts, tmp_path):
        from chartbook.manifest import load_manifest
        from tests.fixtures import _git as run

        root, main, feature = two_checkouts
        run(root / "repos", "clone", "--quiet", str(main), str(root / "repos" / "zz-clone"))
        run(root / "repos" / "zz-clone", "remote", "set-url", "origin", "git@github.com:testorg/first_pipeline.git")
        catalog = _catalog(root / "catalog", '[pipelines]\nmembers = ["../repos/first_pipeline", "../repos/zz-clone"]\n')
        with pytest.warns(UserWarning, match="are checkouts of one repository"):
            loaded = load_manifest(catalog)
        assert Path(loaded["pipelines"]["testorg/first_pipeline"]["pipeline_base_dir"]) == main.resolve()

    def test_an_explicit_entry_wins_over_another_checkout(self, two_checkouts):
        from chartbook.manifest import load_manifest

        root, main, feature = two_checkouts
        catalog = _catalog(
            root / "catalog",
            '[pipelines]\nmembers = ["../repos/*"]\n\n[pipelines."testorg/first_pipeline"]\npath = "../repos/first_pipeline"\n',
        )
        with pytest.warns(UserWarning, match="another checkout of the repository"):
            loaded = load_manifest(catalog)
        assert Path(loaded["pipelines"]["testorg/first_pipeline"]["pipeline_base_dir"]) == main.resolve()

    def test_two_repositories_of_one_id_are_still_refused(self, tmp_path):
        from chartbook.manifest import load_manifest

        # One ID from two hosts: two repositories
        for name, host in (("a", "github.com"), ("b", "gitlab.com")):
            (tmp_path / "repos" / name).mkdir(parents=True)
            (tmp_path / "repos" / name / "chartbook.toml").write_text(f"# {name}\n", encoding="utf-8")
            _repository(tmp_path / "repos" / name, f"https://{host}/testorg/first_pipeline")
        catalog = _catalog(tmp_path / "catalog", '[pipelines]\nmembers = ["../repos/*"]\n')
        with pytest.raises(ValueError, match="two catalog members resolve to the same pipeline"):
            load_manifest(catalog)

    def test_catalog_add_of_both_adds_one(self, two_checkouts):
        from click.testing import CliRunner

        from chartbook.cli import main as cli

        root, main, feature = two_checkouts
        catalog = _catalog(root / "catalog", "[pipelines]\n")
        result = CliRunner().invoke(
            cli, ["catalog", "add", str(root / "repos" / "*"), "--catalog", str(catalog), "-y"]
        )
        assert result.exit_code == 0, result.output
        assert "Already in catalog as 'testorg/first_pipeline' (another checkout of the same repository" in result.output
        import tomli

        assert list(tomli.loads((catalog / "chartbook.toml").read_text(encoding="utf-8"))["pipelines"]) == ["testorg/first_pipeline"]
        # And once it is listed, adding the other checkout adds nothing
        again = CliRunner().invoke(cli, ["catalog", "add", str(feature), "--catalog", str(catalog)])
        assert "another checkout of the same repository" in again.output and "No new pipelines" in again.output

    def test_catalog_add_lists_the_main_worktree_whatever_order_the_folders_come_in(self, two_checkouts):
        """Found by CI: a glob's matches come in the filesystem's order, and on one filesystem the
        worktree came first and became the entry, so the test above failed there and not elsewhere.
        The main worktree is the entry, whatever the order; the other is another checkout of it."""
        import tomli
        from click.testing import CliRunner

        from chartbook.cli import main as cli

        root, main, feature = two_checkouts
        catalog = _catalog(root / "catalog", "[pipelines]\n")
        result = CliRunner().invoke(cli, ["catalog", "add", str(feature), str(main), "--catalog", str(catalog), "-y"])
        assert result.exit_code == 0, result.output
        pipelines = tomli.loads((catalog / "chartbook.toml").read_text(encoding="utf-8"))["pipelines"]
        assert list(pipelines) == ["testorg/first_pipeline"]
        assert (catalog / pipelines["testorg/first_pipeline"]["path"]).resolve() == main.resolve()
        assert f"(another checkout of the same repository, {main.resolve()}): first-feature/" in result.output


class TestAForkIsNotTheSamePipeline:
    """Found by a review: a fork shares its original's first commit, and `update` took its snapshots
    for the original's under a new ID."""

    @pytest.fixture
    def forked(self, tmp_path):
        from chartbook import lock, snapshot
        from tests.fixtures import _git as run

        upstream = _pipeline_with_data(tmp_path / "rates")
        run(upstream, "remote", "add", "origin", "https://github.com/acme/rates")
        clear_git_remote_cache()
        assert snapshot.make(upstream).snapshot.pipeline == "acme/rates"
        run(tmp_path, "clone", "--quiet", str(upstream), str(tmp_path / "fork"))
        fork = tmp_path / "fork"
        run(fork, "remote", "set-url", "origin", "https://github.com/bob/rates")
        clear_git_remote_cache()
        _pipeline_with_data(fork, value=5.0)
        assert snapshot.make(fork).snapshot.pipeline == "bob/rates"
        return tmp_path, lock

    @pytest.mark.parametrize("entry", ["{}", '{ repository = "https://github.com/acme/rates" }'])
    def test_update_says_nothing_of_it(self, forked, entry):
        tmp_path, lock = forked
        second = _depending_on(tmp_path / "second", "acme/rates", entry)
        assert lock.pin(second).count("pinned") == 1
        assert lock.update(second).count("id_changed") == 0

    def test_an_entry_naming_its_repository_is_told_of_one_with_no_address(self, renamed):
        """The pipeline's remote taken away: its snapshots under its new ID name no address, so the
        entry to write leaves out `repository`, which would take none of them."""
        from chartbook import lock, snapshot

        first, second, old, new = renamed
        _depending_on(second, "testorg/first_pipeline", '{ repository = "https://github.com/testorg/first_pipeline" }')
        assert lock.update(second).count("pinned") == 1
        _git(first, "remote", "remove", "origin")
        clear_git_remote_cache()
        _pipeline_with_data(first, value=3.0)
        assert snapshot.make(first).snapshot.pipeline == "first_pipeline"
        (event,) = [e for e in lock.update(second).events if e.status == "id_changed"]
        assert 'write "testorg/first_pipeline" = { id = "first_pipeline" } under' in event.detail
        _depending_on(second, "testorg/first_pipeline", '{ id = "first_pipeline" }')
        assert lock.update(second).count("moved") == 1


class TestWhatCheckSaysOfIds:
    """Found by a review of `chartbook check`'s warnings about IDs."""

    def test_a_fork_at_the_same_commit_is_not_taken_for_the_dependency(self, tmp_path):
        """A fork's clone snapshotted at upstream's commit is noted as a folder of that commit too."""
        from chartbook import lock, snapshot
        from tests.fixtures import _git as run

        upstream = _pipeline_with_data(tmp_path / "rates")
        run(upstream, "remote", "add", "origin", "https://github.com/acme/rates")
        clear_git_remote_cache()
        snapshot.make(upstream)
        run(tmp_path, "clone", "--quiet", str(upstream), str(tmp_path / "fork"))
        fork = tmp_path / "fork"
        run(fork, "remote", "set-url", "origin", "https://github.com/bob/rates")
        clear_git_remote_cache()
        _pipeline_with_data(fork, value=5.0)
        run(fork, "reset", "--quiet", "--hard", "HEAD~1")  # back at upstream's commit
        assert snapshot.make(fork).snapshot.pipeline == "bob/rates"
        second = _depending_on(tmp_path / "second", "acme/rates")
        lock.pin(second)
        assert "calls itself" not in _check(second)

    def test_a_dependency_at_a_commit_is_left_where_it_is(self, renamed):
        first, second, old, new = renamed
        _depending_on(second, "first_pipeline", f'{{ commit = "{old.commit[:7]}" }}')
        assert "calls itself" not in _check(second)

    def test_a_store_at_a_url_is_not_read(self, renamed, monkeypatch):
        """`check` uses no network: a store that is not a folder on this disk is not asked."""
        from chartbook import store

        class Remote:
            def __getattr__(self, name):
                raise AssertionError(f"check asked the store for {name}")

        monkeypatch.setattr(store, "default_store", lambda: Remote())
        first, second, old, new = renamed
        from chartbook import check
        from chartbook.manifest import load_manifest

        check.check_ids(load_manifest(second), second)  # the store is not asked
        output = _check(second)
        assert "Traceback" not in output and "calls itself" not in output

    def test_a_store_that_fails_while_read_says_nothing(self, renamed, monkeypatch):
        from chartbook.store import FolderStore, StoreError

        def fails(self, commit, name):
            raise StoreError("the store went away")

        monkeypatch.setattr(FolderStore, "origins", fails)
        first, second, old, new = renamed
        from chartbook import check
        from chartbook.manifest import load_manifest

        check.check_ids(load_manifest(second), second)  # no error

    def test_a_folder_whose_project_is_not_a_table_gives_no_id(self, renamed):
        first, second, old, new = renamed
        (first / "chartbook.toml").write_text('project = "x"\n', encoding="utf-8")
        from chartbook import check
        from chartbook.manifest import load_manifest

        check.check_ids(load_manifest(second), second)  # no error

    def test_a_repo_url_of_another_repository_is_said(self, tmp_path):
        """A project copied into a new repository with its manifest, `repo_url` and all, would claim the
        original's ID."""
        folder = tmp_path / "rates-copy"
        folder.mkdir()
        (folder / "chartbook.toml").write_text('[project]\nrepo_url = "https://github.com/acme/rates"\n', encoding="utf-8")
        _repository(folder, "https://github.com/me/rates-copy")
        output = _check(folder)
        assert "repo_url: https://github.com/acme/rates is not this folder's git remote" in output
        assert "the pipeline is named after repo_url's repository: acme/rates" in output
        assert "it is me/rates_copy" in output
        # Not when they agree
        (folder / "chartbook.toml").write_text('[project]\nrepo_url = "https://github.com/Me/rates-copy.git"\n', encoding="utf-8")
        assert "repo_url:" not in _check(folder)


class TestWhatTheSecondReviewFound:
    def test_two_repositories_from_one_template_are_two(self, tmp_path):
        """Two repositories made from one template share its first commit, and have two addresses."""
        from chartbook.manifest import load_manifest
        from tests.fixtures import _git as run

        alpha = tmp_path / "repos" / "alpha"
        (alpha / "pipeline").mkdir(parents=True)
        (alpha / "pipeline" / "chartbook.toml").write_text("", encoding="utf-8")
        _repository(alpha, "https://github.com/acme/alpha")
        run(tmp_path / "repos", "clone", "--quiet", str(alpha), str(tmp_path / "repos" / "beta"))
        run(tmp_path / "repos" / "beta", "remote", "set-url", "origin", "https://github.com/acme/beta")
        catalog = _catalog(tmp_path / "catalog", '[pipelines]\nmembers = ["../repos/*/pipeline"]\n')
        with pytest.raises(ValueError, match="two catalog members resolve to the same pipeline"):
            load_manifest(catalog)

    @pytest.fixture
    def transferred(self, tmp_path):
        """`acme/rates`, pinned by `second`; then its repository moves to `neworg`, and its clone's remote with it."""
        from chartbook import lock, snapshot
        from tests.fixtures import _git as run

        first = _pipeline_with_data(tmp_path / "rates")
        run(first, "remote", "add", "origin", "https://github.com/acme/rates")
        clear_git_remote_cache()
        _pipeline_with_data(first, value=1.5)
        assert snapshot.make(first).snapshot.pipeline == "acme/rates"
        second = _depending_on(tmp_path / "second", "acme/rates")
        assert lock.pin(second).count("pinned") == 1
        run(first, "remote", "set-url", "origin", "https://github.com/neworg/rates")
        clear_git_remote_cache()
        _pipeline_with_data(first, value=3.0)
        assert snapshot.make(first).snapshot.pipeline == "neworg/rates"
        return first, second

    def test_a_repository_that_moved_is_said_by_update(self, transferred):
        """Found by a review: matching by address alone lost a repository moved to another owner."""
        from chartbook import lock

        first, second = transferred
        (event,) = [e for e in lock.update(second).events if e.status == "id_changed"]
        assert '"acme/rates" = { id = "neworg/rates" }' in event.detail

    def test_and_by_check(self, transferred):
        first, second = transferred
        output = _check(second)
        assert "acme/rates is the pipeline in" in output and 'Write "acme/rates" = { id = "neworg/rates" }' in output

    def test_a_git_dir_in_the_environment_reaches_no_git_of_chartbook(self, tmp_path, monkeypatch):
        """Found by a review: under GIT_DIR the subfolder pipeline's ID was right and its snapshot's
        subdirectory, its code time and `check`'s repository top were not."""
        from chartbook import check, manifest, snapshot

        top = tmp_path / "monorepo"
        (top / "rates").mkdir(parents=True)
        (top / "rates" / "chartbook.toml").write_text('[dataframes.x]\npath = "x.csv"\n', encoding="utf-8")
        (top / "rates" / "x.csv").write_text("a\n1\n", encoding="utf-8")
        _repository(top, "https://github.com/acme/monorepo")
        monkeypatch.setenv("GIT_DIR", str(top / ".git"))
        taken = snapshot.make(top / "rates").snapshot
        assert (taken.pipeline, taken.subdirectory) == ("acme/rates", "rates")
        assert manifest._git(top / "rates", "rev-parse", "--show-prefix").strip() == "rates/"
        check._repository_top.cache_clear()
        assert check._repository_top(str(top / "rates")) == top.resolve()

    def test_a_folder_named_in_another_case_keeps_its_place(self, tmp_path):
        """Found by a review: on a disk that ignores case, a path written in another case lost its
        subfolder, and two pipelines of one name in two subfolders were taken for one."""
        from chartbook.identity import checkout_of, same_pipeline_checked_out

        top = tmp_path / "monorepo"
        for part in ("a", "b"):
            (top / part / "rates").mkdir(parents=True)
            (top / part / "rates" / "chartbook.toml").write_text("", encoding="utf-8")
        _repository(top, "https://github.com/acme/monorepo")
        other_case = tmp_path / "MONOREPO" / "a" / "rates"
        if not other_case.exists():
            pytest.skip("this disk tells the cases apart")
        assert checkout_of(other_case).subfolder == "a/rates"
        assert not same_pipeline_checked_out(checkout_of(other_case), checkout_of(top / "b" / "rates"))

    def test_a_reference_in_another_case_is_told_the_id(self, tmp_path):
        """Found by a review: with scopes in lowercase, `Neworg/rates` as GitHub writes it found nothing
        and said nothing more."""
        from chartbook import lock, snapshot
        from chartbook.identity import match_pipeline_ref, resolve_pipeline_ref
        from chartbook.resolve import locate_pipeline

        assert match_pipeline_ref(["acme/rates"], "Acme/rates") is None
        with pytest.raises(KeyError, match="Did you mean 'acme/rates'"):
            resolve_pipeline_ref(["acme/rates"], "Acme/rates")
        with pytest.raises(KeyError, match="Did you mean 'acme/rates'"):
            locate_pipeline("Acme/rates", catalog={"acme/rates": str(tmp_path)})
        first = _pipeline_with_data(tmp_path / "rates")
        _git(first, "remote", "add", "origin", "https://github.com/Neworg/rates")
        clear_git_remote_cache()
        assert snapshot.make(first).snapshot.pipeline == "neworg/rates"
        third = _depending_on(tmp_path / "third", "Neworg/rates")
        (problem,) = lock.pin(third).problems
        assert "Did you mean neworg/rates?" in problem.detail

    def test_a_path_or_a_word_is_no_repository(self, tmp_path):
        """Found by a review: a clone of `/srv/rates` derived `srv/rates`, and `repo_url = "TBD"` gave
        `tbd` over a real remote."""
        from chartbook.identity import id_from_address

        assert id_from_address("/srv/rates") is None and id_from_address("file:///srv/rates") is None
        assert id_from_address("TBD") is None
        folder = _repository(tmp_path / "rates", "https://github.com/acme/rates")
        assert derive_pipeline_id({"repo_url": "TBD"}, folder) == "acme/rates"
        source = _repository(tmp_path / "volumes" / "data" / "rates")
        _git(tmp_path, "clone", "--quiet", str(source), str(tmp_path / "copy"))
        clear_git_remote_cache()
        assert derive_pipeline_id({}, tmp_path / "copy") == "copy"

    def test_a_reference_in_gits_short_form_is_an_address(self):
        from chartbook.identity import UnsupportedRegistryError, match_pipeline_ref

        for written in ("org-123@github.com:acme/rates.git", "github.com:Acme/rates.git", "git@github.com:acme/rates"):
            assert match_pipeline_ref(["acme/rates"], written) == "acme/rates", written
        with pytest.raises(UnsupportedRegistryError):
            match_pipeline_ref(["acme/rates"], "localhost:5000/acme/rates")
        with pytest.raises(ValueError):
            match_pipeline_ref(["acme/rates"], "rates:chart")

    def _add(self, catalog, folder):
        from click.testing import CliRunner

        from chartbook.cli import main as cli

        result = CliRunner().invoke(cli, ["catalog", "add", str(folder), "--catalog", str(catalog)])
        assert result.exit_code == 0, result.output
        return result.output

    def test_catalog_add_knows_a_checkout_members_found(self, two_checkouts):
        root, main, feature = two_checkouts
        catalog = _catalog(root / "catalog", '[pipelines]\nmembers = ["../repos/first_pipeline"]\n')
        output = self._add(catalog, feature)
        assert "Already in catalog as 'testorg/first_pipeline' (found by pipelines.members pattern" in output
        assert "another checkout of the same repository" in output
        assert "first-feature" not in (catalog / "chartbook.toml").read_text(encoding="utf-8")

    def test_and_one_listed_under_another_key(self, two_checkouts):
        """A key written before the ID changed, `testorg/first_copy`, still names the pipeline."""
        root, main, feature = two_checkouts
        catalog = _catalog(root / "catalog", '[pipelines."testorg/first_copy"]\npath = "../repos/first_pipeline"\n')
        output = self._add(catalog, feature)
        assert "Already in catalog as 'testorg/first_copy' (another checkout of the same repository" in output
        assert "first-feature" not in (catalog / "chartbook.toml").read_text(encoding="utf-8")

    def test_and_enables_a_disabled_one(self, two_checkouts):
        import tomli

        root, main, feature = two_checkouts
        catalog = _catalog(
            root / "catalog", '[pipelines."testorg/first_pipeline"]\npath = "../repos/first_pipeline"\ndisabled = true\n'
        )
        output = self._add(catalog, feature)
        assert "Re-enabled 'testorg/first_pipeline' (another checkout of the same repository" in output
        entry = tomli.loads((catalog / "chartbook.toml").read_text(encoding="utf-8"))["pipelines"]["testorg/first_pipeline"]
        assert entry == {"path": "../repos/first_pipeline"}
