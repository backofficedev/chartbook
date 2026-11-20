"""A store in a bucket is withdrawn in ChartBook 0.6: one place refuses it, with one line, and nothing is contacted.

A bucket still has the store layout of 0.5, and has not been brought to
this version's (``docs_src/roadmap.md``). The refusal is where a store's
URL becomes a store (:func:`chartbook.store.store_for_url`), so it is the
same through the environment, a settings file, a catalog and the library.
The class itself stays, with its own tests (``tests/test_store_s3.py``),
which make it directly.
"""

from pathlib import Path

import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, data
from chartbook import store as store_module
from chartbook.cli import main
from chartbook.multi_store import Stores
from chartbook.store import StoreNotAvailableError

URL = "s3://team-bucket/chartbook"
LINE = (
    f"The store {URL} is a store in a bucket, and a store in a bucket is not available in ChartBook 0.6: it has not been "
    f"brought to this version's store layout yet, and is on the roadmap. Use a store in a folder ([store] url in your "
    f"settings, or CHARTBOOK_STORE; in a catalog, that store's url): one on a network drive or in a synced folder is "
    f"shared between machines. Nothing is lost: the bucket is as it was, and ChartBook 0.5 still reads and writes it."
)


@pytest.fixture(autouse=True)
def nothing_is_contacted(monkeypatch):
    """No class is looked up for the bucket, so no client is made and nothing is asked of it."""
    monkeypatch.setattr(store_module, "_plugin_store_class", lambda kind: pytest.fail(f"looked for a {kind} store"))


@pytest.fixture
def reader(tmp_path, monkeypatch):
    folder = tmp_path.resolve() / "reader"
    folder.mkdir()
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "acme/reader"}, "dependencies": {"acme/rates": {}}}), encoding="utf-8", newline="\n"
    )
    monkeypatch.chdir(folder)
    return folder


class TestWhereAUrlBecomesAStore:
    def test_the_one_place_refuses_it_with_what_why_what_to_do_and_that_nothing_is_lost(self):
        with pytest.raises(StoreNotAvailableError) as refused:
            store_module.store_for_url(URL)
        assert str(refused.value) == LINE

    def test_a_password_in_its_url_is_not_shown(self):
        with pytest.raises(StoreNotAvailableError) as refused:
            store_module.store_for_url("s3://bucket/p?endpoint=https://user:s3cr3t@minio.example.org")
        assert "s3cr3t" not in str(refused.value) and "The store s3://bucket/p?endpoint=…" in str(refused.value)


class TestThroughTheEnvironment:
    @pytest.mark.parametrize("typed", [["pin"], ["pin", "--check"], ["store", "info"], ["store", "ls"], ["store", "verify"], ["store", "gc", "--dry-run"], ["ls", "versions"], ["store", "migrate", "--dry-run"]])
    def test_a_command_says_the_line_and_exits_1(self, reader, monkeypatch, typed):
        monkeypatch.setenv(config.STORE_ENV_VAR, URL)
        result = CliRunner().invoke(main, typed)
        assert result.exception is None or isinstance(result.exception, SystemExit), repr(result.exception)
        assert result.exit_code == 1 and LINE in result.output.replace("\n", ""), result.output

    def test_a_read_by_the_library_says_it(self, reader, monkeypatch):
        monkeypatch.setenv(config.STORE_ENV_VAR, URL)
        with pytest.raises(Exception) as refused:
            data.path("acme/rates:treasury", project_dir=reader)
        assert "is a store in a bucket, and a store in a bucket is not available in ChartBook 0.6" in str(refused.value)


class TestThroughTheSettingsFile:
    def test_a_command_says_the_line(self, reader, monkeypatch):
        monkeypatch.delenv(config.STORE_ENV_VAR, raising=False)
        settings = config.get_global_settings_path()
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(tomli_w.dumps({"store": {"url": URL}}), encoding="utf-8", newline="\n")
        result = CliRunner().invoke(main, ["store", "info"])
        assert result.exit_code == 1 and LINE in result.output.replace("\n", ""), result.output
        result = CliRunner().invoke(main, ["pin"])
        assert result.exit_code == 1 and LINE in result.output.replace("\n", ""), result.output


class TestThroughACatalog:
    """Every command stops with the line, which names the catalog's store and how to take it out; the other stores are not read meanwhile."""

    @pytest.fixture
    def catalog(self, tmp_path, monkeypatch):
        monkeypatch.delenv(config.STORE_ENV_VAR, raising=False)
        home = config.get_global_config_dir()
        home.mkdir(parents=True, exist_ok=True)
        (tmp_path / "local").mkdir()
        path = home / "catalog.toml"
        path.write_text(
            tomli_w.dumps({"project": {"name": "Catalog"}, "stores": {"mine": {"url": str(tmp_path / "local")}, "team": {"url": URL}}}),
            encoding="utf-8", newline="\n",
        )
        return path

    def test_it_names_the_store_and_the_way_to_take_it_out(self, catalog):
        with pytest.raises(StoreNotAvailableError) as refused:
            Stores.configured()
        assert str(refused.value) == (
            f"{LINE} It is the store 'team' of the catalog {catalog}: `chartbook store remove team` takes it out of the "
            f"catalog, and leaves the bucket as it is."
        )

    @pytest.mark.parametrize("typed", [["store", "info"], ["store", "ls"], ["ls", "stores"], ["ls", "versions"], ["store", "gc", "--dry-run"]])
    def test_no_command_ends_in_a_traceback(self, catalog, typed):
        result = CliRunner().invoke(main, typed)
        assert result.exception is None or isinstance(result.exception, SystemExit), (typed, repr(result.exception))
        assert result.exit_code == 1 and "`chartbook store remove team` takes it out" in result.output.replace("\n", ""), (typed, result.output)

    def test_the_way_out_carried_out_lets_the_others_be_used(self, catalog):
        result = CliRunner().invoke(main, ["store", "remove", "team"])
        assert result.exit_code == 0, result.output
        assert [entry.name for entry in Stores.configured().entries] == ["mine"]
        assert CliRunner().invoke(main, ["store", "ls"]).exit_code == 0

    def test_adding_one_to_a_catalog_is_refused_with_the_line(self, catalog):
        result = CliRunner().invoke(main, ["store", "add", "other", "s3://another-bucket/x"])
        assert result.exception is None or isinstance(result.exception, SystemExit), repr(result.exception)
        assert result.exit_code != 0 and "is a store in a bucket, and a store in a bucket is not available in ChartBook 0.6" in result.output.replace("\n", "")
