"""A table in Databricks, read from another pipeline: pinned by its Delta version.

A snapshot of the pipeline that names the table records the table's version,
not a copy; a pipeline that pins the snapshot reads the table at that
version, after checking it is still the table pinned. A query, a view or a
table with no versions is not pinned, and nothing is copied out of the
warehouse. The warehouse is the stand-in of ``tests/mocked_databricks.py``.
"""

import json

import polars as pl
import pytest
import tomli
import tomli_w

from chartbook import data, lock, snapshot
from chartbook.backends import BackendError
from chartbook.errors import AssetNotPinnedError
from tests import mocked_databricks
from tests.mocked_databricks import Warehouse
from tests.test_model_versions import _commit, _git

HOST = "dbc-test.cloud.databricks.com"
HTTP_PATH = "/sql/1.0/warehouses/abc"
TOKEN = "dapi-test"
URL = f"databricks://{HOST}?http_path={HTTP_PATH}"
CURVE = "workspace.rates.curve"
FIRST = "select * from (values (date '2024-01-01', 4.0), (date '2024-01-02', 4.3)) t(d, y10)"
SECOND = "select * from (values (date '2024-01-01', 4.0), (date '2024-01-02', 4.3), (date '2024-01-03', 4.6)) t(d, y10)"


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    for name in ("DATABRICKS_HTTP_PATH", "CHARTBOOK_SOURCE_WAREHOUSE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABRICKS_HOST", HOST)
    monkeypatch.setenv("DATABRICKS_TOKEN", TOKEN)


@pytest.fixture
def warehouse(monkeypatch):
    found = Warehouse(host=HOST, http_path=HTTP_PATH, token=TOKEN)
    found.table(CURVE, FIRST)
    found.view("workspace.rates.recent", f"select * from {CURVE} where d >= date '2024-01-02'")
    found.table("workspace.rates.plain", "select 1 as a", delta=False)
    return mocked_databricks.install(monkeypatch, found)


@pytest.fixture
def work(tmp_path, warehouse):
    """``rates`` names a Delta table, a view, a table with no versions and a query; ``forecast`` depends on it."""
    work = tmp_path.resolve() / "work"
    rates, forecast = work / "rates", work / "forecast"
    for directory in (rates, forecast):
        (directory / "_data").mkdir(parents=True)
        (directory / "README.md").write_text("# A pipeline\n")
    (rates / "chartbook.toml").write_text(
        tomli_w.dumps(
            {
                "project": {"id": "acme/rates"},
                "sources": {"warehouse": {"backend": "databricks", "url": URL}},
                "dataframes": {
                    "treasury": {"path": "./_data/treasury.parquet", "docs": "A file."},
                    "curve": {"source": "warehouse", "table": CURVE, "docs": "A Delta table."},
                    "recent": {"source": "warehouse", "table": "workspace.rates.recent", "docs": "A view."},
                    "plain": {"source": "warehouse", "table": "workspace.rates.plain", "docs": "No versions."},
                    "top": {"source": "warehouse", "query": f"select max(y10) as top from {CURVE}", "docs": "A query."},
                },
            }
        )
    )
    pl.DataFrame({"d": ["2024-01-01"], "r": [4.1]}).write_parquet(rates / "_data" / "treasury.parquet")
    (forecast / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "acme/forecast"}, "dependencies": {"rates": {"path": "../rates"}}})
    )
    _git(work, "init", "--quiet", "-b", "main")
    (work / ".gitignore").write_text("_data/\n_models/\n_output/\n_docs*/\ndocs/\nchartbook.lock\n")
    _commit(work)
    return rates, forecast


class TestTheSnapshot:
    def test_a_delta_table_is_kept_by_its_version(self, work, warehouse):
        rates, _ = work
        taken = snapshot.make(rates).snapshot
        curve = taken.assets["curve"]
        table_id = warehouse.tables[CURVE]["id"]
        written = "2026-10-01T01:00:00+00:00"
        assert curve["table_version"] == {"version": 0, "table_id": table_id, "name": CURVE, "written_at": written}
        held = snapshot.default_store().object_path(curve["content_hash"])
        assert sorted(p.name for p in held.iterdir()) == ["curve.version.json"]
        assert json.loads((held / "curve.version.json").read_text()) == {
            "backend": "databricks", "identifier": CURVE, "table_id": table_id, "version": 0, "written_at": written,
        }
        # Its rows were never asked for whole: only described, as the index describes any table
        assert "select * from `workspace`.`rates`.`curve`" not in warehouse.queries

    def test_what_has_no_versions_is_not_copied_out_of_the_warehouse(self, work, warehouse):
        rates, _ = work
        report = snapshot.make(rates)
        assets = report.snapshot.assets
        reasons = dict(report.not_pinned)
        assert report.not_built == []
        for name in ("recent", "plain", "top"):
            assert "content_hash" not in assets[name] and "table_version" not in assets[name]
        assert "keeps no versions to pin (a view, or a table that is not Delta)" in reasons["acme/rates:recent"]
        assert "keeps no versions to pin" in reasons["acme/rates:plain"]
        assert "a query in a warehouse is not copied out of it" in reasons["acme/rates:top"]
        # Not a row of any of them was asked for
        assert not any("order by all" in q or q.startswith("select max") for q in warehouse.queries)

    def test_a_name_in_two_parts_is_pinned_in_full(self, work, warehouse, monkeypatch):
        rates, forecast = work
        config = tomli.loads((rates / "chartbook.toml").read_text())
        config["sources"]["warehouse"]["url"] = URL + "&catalog=workspace"
        config["dataframes"]["curve"]["table"] = "rates.curve"
        (rates / "chartbook.toml").write_text(tomli_w.dumps(config))
        _commit(rates.parent)
        assert snapshot.make(rates).snapshot.assets["curve"]["table_version"]["name"] == CURVE
        lock.pin(forecast)
        # The reader's connection starts in another catalog, which has a rates.curve of its own,
        # and reads the table pinned
        warehouse.table("elsewhere.rates.curve", "select 9 as x")
        monkeypatch.setenv("CHARTBOOK_SOURCE_WAREHOUSE_URL", f"databricks://token:{TOKEN}@{HOST}?http_path={HTTP_PATH}&catalog=elsewhere")
        monkeypatch.chdir(forecast)
        assert data.load("rates:curve").collect().height == 2
        assert warehouse.queries[-1] == "select * from `workspace`.`rates`.`curve` VERSION AS OF 0"

    @pytest.mark.parametrize("statement", ["describe history", "VERSION AS OF 0 limit 0"])
    def test_an_error_while_pinning_is_said_and_nothing_is_copied(self, work, warehouse, statement):
        rates, _ = work
        warehouse.fail(statement, "[SESSION_EXPIRED] The session has expired.")
        report = snapshot.make(rates)
        assert "could not be read: [SESSION_EXPIRED]" in dict(report.not_built)["acme/rates:curve"]
        assert "content_hash" not in report.snapshot.assets["curve"]

    def test_a_table_whose_versions_cannot_be_read_is_not_pinned(self, work, warehouse):
        rates, _ = work
        warehouse.fail("VERSION AS OF 0 limit 0", "[UNSUPPORTED_FEATURE.TIME_TRAVEL] Time travel is not supported on a streaming table. SQLSTATE: 0A000")
        report = snapshot.make(rates)
        assert "keeps no versions to pin" in dict(report.not_pinned)["acme/rates:curve"]

    def test_an_unchanged_table_is_the_same_snapshot(self, work):
        rates, _ = work
        assert snapshot.make(rates).made is True
        assert snapshot.make(rates).made is False

    def test_a_new_version_is_a_new_snapshot(self, work, warehouse):
        rates, _ = work
        first = snapshot.make(rates).snapshot.assets["curve"]
        warehouse.table(CURVE, SECOND)
        second = snapshot.make(rates)
        assert second.made is True
        assert second.snapshot.assets["curve"]["table_version"]["version"] == 1
        assert second.snapshot.assets["curve"]["content_hash"] != first["content_hash"]

    def test_with_no_token_it_is_recorded_as_not_built_and_says_why(self, work, monkeypatch):
        rates, _ = work
        monkeypatch.delenv("DATABRICKS_TOKEN")
        report = snapshot.make(rates)
        reasons = dict(report.not_built)
        assert "has no token" in reasons["acme/rates:curve"]
        assert "content_hash" not in report.snapshot.assets["curve"]
        assert report.snapshot.assets["treasury"]["content_hash"]


class TestAnotherPipelineReadsIt:
    def test_pin_then_load_at_the_pinned_version(self, work, warehouse, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        report = lock.pin(forecast)
        statuses = {e.asset: e.status for e in report.events if e.asset}
        assert statuses == {
            "rates:treasury": "pinned", "rates:curve": "pinned",
            "rates:recent": "never_pinned", "rates:plain": "never_pinned", "rates:top": "never_pinned",
        }
        monkeypatch.chdir(forecast)
        assert data.load("rates:curve").collect().height == 2
        assert warehouse.queries[-1] == "select * from `workspace`.`rates`.`curve` VERSION AS OF 0"
        # The table moves on; the pin does not
        warehouse.table(CURVE, SECOND)
        assert data.load("rates:curve").collect().height == 2
        # A view is not pinned, and says why
        with pytest.raises(AssetNotPinnedError, match="is a table in a warehouse, and a snapshot does not pin it: it keeps no versions"):
            data.load("rates:recent")
        with pytest.raises(AssetNotPinnedError, match="is a query in a warehouse, and a snapshot does not pin it"):
            data.load("rates:top")

    def test_update_moves_to_the_new_version(self, work, warehouse, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        warehouse.table(CURVE, SECOND)
        snapshot.make(rates)
        assert any(e.status == "stale" and e.asset == "rates:curve" for e in lock.pin(forecast).events)
        report = lock.update(forecast)
        assert any(e.status == "moved" and e.asset == "rates:curve" for e in report.events)
        monkeypatch.chdir(forecast)
        assert data.load("rates:curve").collect().height == 3

    def test_sql_names_the_version(self, work, warehouse, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        assert data.ref("rates:curve") == "`workspace`.`rates`.`curve` VERSION AS OF 0"
        assert data.sql("select count(*) as n from {rates:curve}").collect()["n"].to_list() == [2]

    def test_it_has_no_path(self, work, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        with pytest.raises(Exception, match="table"):
            data.path("rates:curve")

    def test_frozen_and_the_lineage_check_pass_over_what_is_never_pinned(self, work):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        assert lock.read_lock(forecast / lock.LOCK_FILE).assets["rates:recent"]["not_pinned"]
        assert lock.verify(forecast).problems == []
        assert snapshot.lineage_gaps(forecast) == []

    def test_frozen_still_says_a_table_that_could_not_be_pinned(self, work, warehouse):
        rates, forecast = work
        warehouse.fail("describe history", "[SESSION_EXPIRED] The session has expired.")
        snapshot.make(rates)
        lock.pin(forecast)
        assert [p.asset for p in lock.verify(forecast).problems] == ["rates:curve"]

    def test_a_version_the_table_no_longer_keeps_says_what_to_do(self, work, warehouse, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        warehouse.table(CURVE, SECOND)
        warehouse.vacuum(CURVE, keep_from=1)
        monkeypatch.chdir(forecast)
        with pytest.raises(BackendError) as error:
            data.load("rates:curve")
        for said in (
            "Cannot time travel", "pinned at version 0", "in a new snapshot (`chartbook snapshot` there)",
            "`chartbook update` here pins that", "delta.deletedFileRetentionDuration",
        ):
            assert said in str(error.value)
        assert warehouse.open() == []

    def test_what_the_message_says_to_do_works(self, work, warehouse, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        warehouse.table(CURVE, SECOND)
        warehouse.vacuum(CURVE, keep_from=1)
        # An update alone has nothing newer to move to
        assert {e.status for e in lock.update(forecast).events if e.asset == "rates:curve"} == {"kept"}
        snapshot.make(rates)
        lock.update(forecast)
        monkeypatch.chdir(forecast)
        assert data.load("rates:curve").collect().height == 3

    def test_a_table_made_again_under_the_same_name_is_not_read_as_the_one_pinned(self, work, warehouse, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        warehouse.replace(CURVE, SECOND)
        monkeypatch.chdir(forecast)
        for read in (
            lambda: data.load("rates:curve"),
            lambda: data.sql("select count(*) as n from {rates:curve}"),
            lambda: data.ref("rates:curve"),
        ):
            with pytest.raises(BackendError, match="is not the table that was pinned at version 0.*in a new snapshot"):
                read()

    def test_a_table_made_again_with_its_history_still_serves_its_pins(self, work, warehouse, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        warehouse.rebuild(CURVE, SECOND)
        monkeypatch.chdir(forecast)
        assert data.load("rates:curve").collect().height == 2
        assert data.sql("select count(*) as n from {rates:curve}").collect()["n"].to_list() == [2]

    def test_reading_needs_this_machines_own_settings(self, work, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        monkeypatch.setenv("DATABRICKS_HOST", "other.example.com")
        with pytest.raises(BackendError, match=f"names the workspace {HOST}, and this machine's, from DATABRICKS_HOST, is other.example.com"):
            data.load("rates:curve")


class TestAPinIsTheLockfilesAndTheStoreMustAgree:
    @pytest.mark.parametrize(
        "change",
        [
            {"version": "0; drop table x"},
            {"version": -1},
            {"version": True},
            {"version": 1},
            {"identifier": "a\nb"},
            {"identifier": "a.b.c.d"},
            {"identifier": "workspace.hr.salaries"},
            {"table_id": "x' or 1=1"},
            {"written_at": "2020-01-01T00:00:00+00:00"},
            {"backend": "duckdb"},
        ],
    )
    def test_a_store_file_changed_since_the_pin_is_refused(self, work, monkeypatch, change):
        rates, forecast = work
        taken = snapshot.make(rates).snapshot
        lock.pin(forecast)
        held = snapshot.default_store().object_path(taken.assets["curve"]["content_hash"]) / "curve.version.json"
        pinned = {**json.loads(held.read_text()), **change}
        held.chmod(0o644)
        held.write_text(json.dumps(pinned))
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="are not both ChartBook's and do not agree"):
            data.load("rates:curve")

    @pytest.mark.parametrize(
        "change",
        [
            {"location": {"kind": "query", "source": "warehouse", "backend": "databricks", "url": URL, "sql": "select 1"}},
            {"location": {"kind": "table", "source": "warehouse", "backend": "duckdb", "url": "duckdb:///x.duckdb", "identifier": CURVE}},
            {"table_version": {"version": 0}},
        ],
    )
    def test_a_lockfile_record_that_is_not_a_versioned_table_is_refused(self, work, monkeypatch, change):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        path = forecast / lock.LOCK_FILE
        locked = lock.read_lock(path)
        locked.assets["rates:curve"].update(change)
        lock.write_lock(locked, path)
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="are not both ChartBook's and do not agree"):
            data.load("rates:curve")

    def test_a_version_file_beside_a_pinned_copy_is_not_read(self, tmp_path):
        from chartbook.resolve import FileLocation, _held
        from chartbook.store import FolderStore

        store = FolderStore(tmp_path / "store")
        made = tmp_path / "made"
        made.mkdir()
        pl.DataFrame({"a": [1]}).write_parquet(made / "t.parquet")
        (made / "t.version.json").write_text(json.dumps({"backend": "duckdb", "identifier": "secret", "table_id": "x", "version": 0}))
        stored = store.put(made)
        record = {
            "id": "rates:t", "ref": {"kind": "dataframe", "name": "t", "pipeline": "rates"},
            "location": {"kind": "table", "source": "local", "backend": "duckdb", "url": "duckdb:///x.duckdb", "identifier": "t"},
            "content_hash": stored.content_hash,
        }
        location = _held(store, record)
        assert isinstance(location, FileLocation) and location.path.name == "t.parquet"


class TestWhatTheSecondReviewFound:
    def test_a_read_through_no_lockfile_does_not_take_a_version_pin_from_the_store(self, work, tmp_path, monkeypatch):
        """A record read from the store is the store's to say: it could name any table the reader can read."""
        rates, _ = work
        snapshot.make(rates)
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        monkeypatch.chdir(scratch)
        with pytest.raises(AssetNotPinnedError, match="read only through this pipeline.s own lockfile: declare its pipeline in \\[dependencies\\]"):
            data.load("acme/rates:curve")

    @pytest.mark.parametrize(
        "message",
        [
            "[INSUFFICIENT_PERMISSIONS] Insufficient privileges on schema `workspace`.`unsupported_feeds`. SQLSTATE: 42501",
            "[DELTA_UNSUPPORTED_SOMETHING_TRANSIENT] not supported right now. SQLSTATE: 40000",
        ],
    )
    def test_an_error_that_only_mentions_unsupported_is_an_error(self, work, warehouse, message):
        rates, _ = work
        warehouse.fail("describe history", message)
        report = snapshot.make(rates)
        assert "content_hash" not in report.snapshot.assets["curve"]
        assert "not_pinned" not in report.snapshot.assets["curve"]
        assert "could not be read" in dict(report.not_built)["acme/rates:curve"]

    def test_a_row_filter_is_a_table_with_no_versions(self, work, warehouse):
        rates, _ = work
        warehouse.fail(
            "VERSION AS OF 0 limit 0",
            "[FGAC_TIME_TRAVEL_NOT_SUPPORTED.PER_TABLE_RLS_CM] Cannot time travel to the specified version or "
            "timestamp of this table. SQLSTATE: 0A000",
        )
        report = snapshot.make(rates)
        assert report.snapshot.assets["curve"]["not_pinned"]
        assert "acme/rates:curve" in dict(report.not_pinned)

    def test_an_error_in_connecting_is_never_no_versions(self, work, monkeypatch):
        import sys

        def refuse(**arguments):
            raise mocked_databricks.RequestError("[SSL: UNSUPPORTED_PROTOCOL] unsupported protocol SQLSTATE: 0A000")

        monkeypatch.setattr(sys.modules["databricks.sql"], "connect", refuse)
        rates, _ = work
        report = snapshot.make(rates)
        assert "not_pinned" not in report.snapshot.assets["curve"]
        assert "could not be read" in dict(report.not_built)["acme/rates:curve"]

    def test_a_pipeline_of_views_alone_is_snapshotted_and_pinned(self, tmp_path, warehouse):
        work = tmp_path.resolve() / "views"
        views, reader = work / "views", work / "reader"
        for directory in (views, reader):
            directory.mkdir(parents=True)
            (directory / "README.md").write_text("# A pipeline\n")
        (views / "chartbook.toml").write_text(
            tomli_w.dumps(
                {
                    "project": {"id": "acme/views"},
                    "sources": {"warehouse": {"backend": "databricks", "url": URL}},
                    "dataframes": {"recent": {"source": "warehouse", "table": "workspace.rates.recent", "docs": "A view."}},
                }
            )
        )
        (reader / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "acme/reader"}, "dependencies": {"views": {"path": "../views"}}}))
        _git(work, "init", "--quiet", "-b", "main")
        (work / ".gitignore").write_text("_data/\nchartbook.lock\n")
        _commit(work)
        report = snapshot.make(views)
        assert report.made and report.not_built == [] and [a for a, _ in report.not_pinned] == ["acme/views:recent"]
        lock.pin(reader)
        assert lock.verify(reader).problems == []

    def test_the_history_is_read_back_to_the_pinned_version_and_no_further(self, work, warehouse, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        for _ in range(3):
            warehouse.table(CURVE, SECOND)
        warehouse.rebuild(CURVE, SECOND)
        monkeypatch.chdir(forecast)
        assert data.load("rates:curve").collect().height == 2
        histories = [q for q in warehouse.queries if q.startswith("describe history")]
        assert histories and all(" limit " in q for q in histories)
        assert histories[-1].endswith("limit 5")

    def test_a_table_replaced_after_the_load_is_refused_when_collected(self, work, warehouse, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        frame = data.load("rates:curve")
        warehouse.replace(CURVE, SECOND)
        with pytest.raises((pl.exceptions.ComputeError, BackendError), match="is not the table that was pinned"):
            frame.collect()

    def test_a_table_that_is_gone_says_what_moves_the_pin(self, work, warehouse, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        warehouse.duck.execute(f"drop view {CURVE}")
        del warehouse.tables[CURVE]
        monkeypatch.chdir(forecast)
        with pytest.raises(BackendError, match="(?s)TABLE_OR_VIEW_NOT_FOUND.*pinned at version 0. The pipeline that names the table"):
            data.load("rates:curve")

    def test_with_no_backend_here_the_message_says_to_install_it(self, work, monkeypatch):
        from chartbook import backends

        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        monkeypatch.setattr(backends, "backend_class", lambda name: None)
        with pytest.raises(AssetNotPinnedError, match=r"nothing here reads one: install its backend \(pip install chartbook\[databricks\]\)"):
            data.load("rates:curve")

    def test_a_backend_that_pins_by_version_and_checks_nothing_is_not_read(self, work, monkeypatch):
        from chartbook import backends
        from chartbook.backends.databricks import DatabricksBackend

        class Careless(DatabricksBackend):
            check_pin = backends.Backend.check_pin

        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        monkeypatch.setattr(backends, "backend_class", lambda name: Careless)
        with pytest.raises(AssetNotPinnedError, match="do not agree"):
            data.load("rates:curve")

    def test_a_name_the_warehouse_does_not_give_in_full_is_put_in_the_sessions_catalog(self, work, warehouse):
        rates, _ = work
        config = tomli.loads((rates / "chartbook.toml").read_text())
        config["sources"]["warehouse"]["url"] = URL + "&catalog=workspace&schema=rates"
        config["dataframes"]["curve"]["table"] = "curve"
        (rates / "chartbook.toml").write_text(tomli_w.dumps(config))
        _commit(rates.parent)
        warehouse.detail_without_name = True
        assert snapshot.make(rates).snapshot.assets["curve"]["table_version"]["name"] == CURVE

    def test_pin_says_why_a_view_is_not_pinned(self, work):
        rates, forecast = work
        snapshot.make(rates)
        events = {e.asset: e for e in lock.pin(forecast).events if e.asset}
        assert "keeps no versions to pin" in events["rates:recent"].detail

    def test_check_warns_of_a_model_trained_on_what_is_never_pinned(self, work):
        import warnings

        from chartbook.check import check_model_lineage
        from chartbook.manifest import load_manifest

        rates, forecast = work
        snapshot.make(rates)
        config = tomli.loads((forecast / "chartbook.toml").read_text())
        config["models"] = {"m": {"path": "./_models/m.json", "trained_on": ["rates:recent"], "docs": "A model."}}
        (forecast / "chartbook.toml").write_text(tomli_w.dumps(config))
        lock.pin(forecast)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            check_model_lineage(load_manifest(forecast), forecast)
        assert any("'rates:recent' is in a warehouse and never pinned" in str(w.message) for w in caught)


class TestWhatTheThirdReviewFound:
    def test_a_store_record_naming_another_table_than_declared_is_not_read_on_first_read(self, work, warehouse, monkeypatch):
        """A record from the store may name any table; the lockfile shows the declared one, and a read must not differ."""
        from chartbook.store import FolderStore

        rates, forecast = work
        warehouse.table("workspace.hr.salaries", "select 'alice' as name, 250000 as salary")
        taken = snapshot.make(rates).snapshot
        store = snapshot.default_store()
        salaries = warehouse.tables["workspace.hr.salaries"]
        forged_dir = rates.parent.parent / "forged"
        forged_dir.mkdir()
        forged = {"backend": "databricks", "identifier": "workspace.hr.salaries", "table_id": salaries["id"],
                  "version": 0, "written_at": salaries["versions"][0][1].isoformat()}
        (forged_dir / "curve.version.json").write_text(json.dumps(forged, sort_keys=True) + "\n")
        stored = store.put(forged_dir / "curve.version.json", links=("copy",))
        record_path = taken.path
        written = json.loads(record_path.read_text())
        curve = next(record for record in written["records"] if record["id"].endswith(":curve"))
        curve["content_hash"] = stored.content_hash
        curve["table_version"] = {"version": 0, "table_id": salaries["id"], "name": "workspace.hr.salaries", "written_at": forged["written_at"]}
        record_path.chmod(0o644)
        record_path.write_text(json.dumps(written))
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="do not agree"):
            data.load("rates:curve")
        assert not any("hr`.`salaries" in q for q in warehouse.queries)

    def test_a_frame_of_sql_is_checked_again_when_collected(self, work, warehouse, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        frame = data.sql("select * from {rates:curve}")
        warehouse.replace(CURVE, SECOND)
        with pytest.raises((pl.exceptions.ComputeError, BackendError), match="is not the table that was pinned"):
            frame.collect()

    @pytest.mark.parametrize(
        "message",
        [
            "[UNSUPPORTED_FEATURE.SOMETHING_ELSE] Not here. SQLSTATE: 0A000",
            "[DELTA_UNSUPPORTED_TIME_TRAVEL_BEYOND_DELETED_FILE_RETENTION_DURATION] Too old. SQLSTATE: 0AKDC",
            "[UC_COMMAND_NOT_SUPPORTED_IN_SERVERLESS] Not on this warehouse. SQLSTATE: 0AKUC",
            "Table x.SQLSTATE: 0A000 cannot be found. SQLSTATE: 42P01",
        ],
    )
    def test_only_what_says_the_table_has_no_versions_leaves_it_never_pinned(self, work, warehouse, message):
        rates, _ = work
        warehouse.fail("VERSION AS OF 0 limit 0", message)
        report = snapshot.make(rates)
        assert "not_pinned" not in report.snapshot.assets["curve"]
        assert "could not be read" in dict(report.not_built)["acme/rates:curve"]

    def test_a_long_history_since_a_pin_is_refused_and_a_short_one_is_read_once(self, work, warehouse, monkeypatch):
        from chartbook.backends import databricks

        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        for _ in range(3):
            warehouse.table(CURVE, SECOND)
        warehouse.rebuild(CURVE, SECOND)
        monkeypatch.chdir(forecast)
        monkeypatch.setattr(databricks, "_HISTORY_CHECKED", set())
        monkeypatch.setattr(databricks, "HISTORY_LIMIT", 3)
        with pytest.raises(BackendError, match="4 versions have been written since: too many"):
            data.load("rates:curve")
        monkeypatch.setattr(databricks, "HISTORY_LIMIT", 10_000)
        data.load("rates:curve").collect()
        before = sum(q.startswith("describe history") for q in warehouse.queries)
        data.load("rates:curve").collect()
        assert sum(q.startswith("describe history") for q in warehouse.queries) == before

    def test_a_snapshot_with_nothing_built_says_why(self, tmp_path, warehouse, monkeypatch):
        from chartbook.snapshot import SnapshotError

        work = tmp_path.resolve() / "only"
        only = work / "only"
        only.mkdir(parents=True)
        (only / "README.md").write_text("# A pipeline\n")
        (only / "chartbook.toml").write_text(
            tomli_w.dumps(
                {
                    "project": {"id": "acme/only"},
                    "sources": {"warehouse": {"backend": "databricks", "url": URL}},
                    "dataframes": {"curve": {"source": "warehouse", "table": CURVE, "docs": "A table."}},
                }
            )
        )
        _git(work, "init", "--quiet", "-b", "main")
        _commit(work)
        monkeypatch.delenv("DATABRICKS_TOKEN")
        with pytest.raises(SnapshotError, match="has built nothing it declares.*has no token"):
            snapshot.make(only)

    def test_a_backend_that_pins_nothing_by_version_says_so(self, work, monkeypatch):
        from chartbook import backends
        from chartbook.backends.databricks import DatabricksBackend

        class Plain(DatabricksBackend):
            version_of = backends.Backend.version_of

        monkeypatch.setattr(backends, "backend_class", lambda name: Plain if name == "databricks" else None)
        rates, _ = work
        report = snapshot.make(rates)
        assert "its backend, databricks, pins nothing by version" in dict(report.not_pinned)["acme/rates:curve"]

    def test_pin_says_never_pinned_and_why_every_time(self, work):
        from click.testing import CliRunner

        from chartbook.cli import main

        rates, forecast = work
        snapshot.make(rates)
        for _ in range(2):
            result = CliRunner().invoke(main, ["pin", "--project-dir", str(forecast)])
            assert "never pinned: rates:recent: it keeps no versions to pin" in result.output
            assert "not built: rates:recent" not in result.output
