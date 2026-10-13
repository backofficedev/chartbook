"""Tests for references to another pipeline's assets: ``pipeline:name``.

This is the fourth part of step 3 of ``docs_src/design/overview.md``, and
the one the other three were for. A reference to an asset of a declared
dependency resolves through ``chartbook.lock`` to the pinned copy in the
store, and never to the other pipeline's working directory.
"""

import glob
import json
import os
from pathlib import Path

import jsonschema
import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import assets, config, data, hashing, index, lock, models
from chartbook import resolve as resolve_module
from chartbook.cli import main
from chartbook.errors import AssetNotPinnedError, DependencyNotDeclaredError
from chartbook.identity import UnsupportedRegistryError, UnsupportedRevisionError
from chartbook.manifest import load_manifest
from chartbook.refs import KindMismatchError
from chartbook.resolve import UnsupportedReferenceError, resolve
from chartbook.store import Store
from tests.fixtures import create_catalog_project, create_pipeline_project

HELLO = "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def _write_manifest(directory: Path, table: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table))


def _rewrite(path: Path, content: bytes) -> None:
    """Write new bytes into the file that is there, as ``to_parquet`` does."""
    with open(path, "r+b") as f:
        f.write(content)
        f.truncate()


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    """This test's store. Resolving a reference uses the user's, so point that here."""
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    return Store(work / "store")


@pytest.fixture
def rates(work):
    """An upstream pipeline with one asset of each shape."""
    directory = work / "rates"
    _write_manifest(
        directory,
        {
            "project": {"id": "rates"},
            "dataframes": {
                "treasury": {"path": "./_data/treasury.parquet", "docs": "d"},
                "by_year": {"path": "./_data/by_year/**/*.parquet", "docs": "d"},
                "not_built": {"path": "./_data/not_built.parquet", "docs": "d"},
            },
            "charts": {
                "curve": {"path": "./_output/curve.html", "dataframe": "treasury", "docs": "d"}
            },
            "models": {"ar1": {"path": "./_models/ar1"}},
        },
    )
    (directory / "_data" / "by_year" / "year=2023").mkdir(parents=True)
    (directory / "_data" / "by_year" / "year=2024").mkdir()
    (directory / "_data" / "treasury.parquet").write_bytes(b"hello")
    (directory / "_data" / "by_year" / "year=2023" / "part-0.parquet").write_bytes(b"a" * 10)
    (directory / "_data" / "by_year" / "year=2024" / "part-0.parquet").write_bytes(b"b" * 20)
    (directory / "_output").mkdir()
    (directory / "_output" / "curve.html").write_bytes(b"<html>curve</html>")
    (directory / "_models" / "ar1" / "weights").mkdir(parents=True)
    (directory / "_models" / "ar1" / "config.json").write_bytes(b"{}")
    (directory / "_models" / "ar1" / "weights" / "best.pt").write_bytes(b"w" * 100)
    return directory


@pytest.fixture
def downstream(work, rates):
    """A pipeline that depends on ``rates`` as ``acme/rates``. Not pinned yet."""
    directory = work / "downstream"
    _write_manifest(
        directory,
        {
            "project": {"id": "downstream"},
            "dependencies": {"acme/rates": {"path": "../rates"}},
        },
    )
    return directory


@pytest.fixture
def pinned(downstream, store):
    """The downstream pipeline, with its dependency pinned."""
    lock.pin(downstream, store)
    return downstream


class TestResolving:
    def test_another_pipelines_dataframe_is_its_pinned_copy(self, pinned, store, rates):
        path = data.path("rates:treasury", project_dir=pinned)
        assert path == store.get(HELLO) / "treasury.parquet"
        assert path.read_bytes() == b"hello"
        # In the store, not in the other pipeline's working directory
        assert rates not in path.parents
        assert not path.samefile(rates / "_data" / "treasury.parquet")

    def test_the_scope_may_be_given_or_left_off(self, pinned):
        short = assets.path("rates:treasury", project_dir=pinned)
        assert assets.path("acme/rates:treasury", project_dir=pinned) == short
        assert assets.path("rates:dataframe/treasury", project_dir=pinned) == short
        assert assets.path("rates:treasury", kind="dataframe", project_dir=pinned) == short

    def test_every_kind_of_asset(self, pinned):
        chart = assets.path("rates:chart/curve", project_dir=pinned)
        assert chart.name == "curve.html" and chart.read_bytes() == b"<html>curve</html>"
        assert assets.path("rates:curve", kind="chart", project_dir=pinned) == chart

    def test_a_partitioned_dataframe_keeps_its_glob(self, pinned, store):
        path = data.path("rates:by_year", project_dir=pinned)
        held = store.get(lock.read_lock(pinned).assets["acme/rates:by_year"]["content_hash"])
        assert path == held / "**" / "*.parquet"
        found = sorted(Path(p).relative_to(held).as_posix() for p in glob.glob(str(path), recursive=True))
        assert found == ["year=2023/part-0.parquet", "year=2024/part-0.parquet"]

    def test_a_model_that_is_a_directory_is_the_objects_directory(self, pinned, store):
        path = models.path("rates:ar1", project_dir=pinned)
        record = lock.read_lock(pinned).assets["acme/rates:model/ar1"]
        assert path == store.get(record["content_hash"])
        assert (path / "config.json").read_bytes() == b"{}"
        assert (path / "weights" / "best.pt").stat().st_size == 100
        # The lockfile lists a directory's files, as the index lists a model's
        assert [f["path"] for f in record["files"]] == ["config.json", "weights/best.pt"]
        assert assets.path("rates:model/ar1", project_dir=pinned) == path

    def test_a_directory_pinned_before_files_were_listed_still_resolves(self, pinned, store):
        locked = lock.read_lock(pinned)
        del locked.assets["acme/rates:model/ar1"]["files"]
        lock.write_lock(locked, pinned / lock.LOCK_FILE)
        path = models.path("rates:ar1", project_dir=pinned)
        assert (path / "config.json").is_file()

    def test_the_front_doors_still_answer_for_one_kind_each(self, pinned):
        with pytest.raises(KindMismatchError, match="data.path\\(\\) answers for dataframes only"):
            data.path("rates:chart/curve", project_dir=pinned)
        with pytest.raises(KindMismatchError, match="models.path\\(\\) answers for models only"):
            models.path("rates:chart/curve", project_dir=pinned)

    def test_it_is_found_from_the_calling_file_like_a_local_one(self, pinned, monkeypatch):
        (pinned / "src").mkdir()
        monkeypatch.chdir(pinned / "src")
        assert data.path("rates:treasury").name == "treasury.parquet"

    def test_resolve_returns_a_file_location(self, pinned, store):
        location = resolve("rates:treasury", start_dirs=[pinned])
        assert location.kind == "file"
        assert location.path == store.get(HELLO) / "treasury.parquet"


class TestFrozen:
    """The step's "Done when": editing the upstream does not change what is read."""

    def test_rewriting_the_upstream_does_not_change_what_is_read(self, pinned, rates):
        before = data.path("rates:treasury", project_dir=pinned)
        _rewrite(rates / "_data" / "treasury.parquet", b"new numbers")
        after = data.path("rates:treasury", project_dir=pinned)
        assert after == before and after.read_bytes() == b"hello"

    def test_until_chartbook_update(self, pinned, rates, store):
        before = data.path("rates:treasury", project_dir=pinned)
        _rewrite(rates / "_data" / "treasury.parquet", b"new numbers")
        lock.pin(pinned, store)  # pinning again moves nothing
        assert data.path("rates:treasury", project_dir=pinned) == before

        lock.update(pinned, store=store)
        after = data.path("rates:treasury", project_dir=pinned)
        assert after != before and after.read_bytes() == b"new numbers"
        # The old copy is as it was, for anything still reading it
        assert before.read_bytes() == b"hello"

    def test_the_pinned_copy_is_not_to_be_written(self, pinned):
        path = data.path("rates:treasury", project_dir=pinned)
        assert not os.access(path, os.W_OK)

    def test_this_pipelines_own_assets_are_still_live(self, work, store):
        project = create_pipeline_project(work / "own").resolve()
        path = data.path("dataframe_0", project_dir=project)
        assert path == project / "_data" / "test_pipeline" / "dataframe_0.parquet"
        assert not store.root.exists()


class TestWhatIsMissing:
    """Each thing that can be missing says which, and what to run."""

    def test_a_pipeline_that_is_not_a_dependency(self, pinned):
        with pytest.raises(DependencyNotDeclaredError) as e:
            data.path("macro:gdp", project_dir=pinned)
        error = e.value
        assert (error.reference, error.pipeline) == ("macro:gdp", "macro")
        assert error.manifest_path == pinned / "chartbook.toml"
        assert error.declared == ["acme/rates"]
        message = str(error)
        assert "names an asset of the pipeline 'macro', which is not declared" in message
        assert '    "macro" = { path = "../macro" }' in message
        assert "    $ chartbook pin" in message
        assert "Declared dependencies: acme/rates" in message
        assert isinstance(error, LookupError)

    def test_a_misspelt_dependency_is_suggested(self, pinned):
        with pytest.raises(DependencyNotDeclaredError, match="Did you mean 'acme/rates'"):
            data.path("acme/rate:treasury", project_dir=pinned)

    def test_the_catalog_is_asked_where_an_undeclared_pipeline_is(self, pinned, work, monkeypatch):
        """The chain's second step makes the error useful; it grants no access."""
        catalog = create_catalog_project(work / "cat")
        monkeypatch.setattr(
            resolve_module, "get_default_catalog_path", lambda: catalog / "chartbook.toml"
        )
        with pytest.raises(DependencyNotDeclaredError) as e:
            data.path("pipeline_a:dataframe_0", project_dir=pinned)
        message = str(e.value)
        assert "Your catalog has it, as 'pipeline_a'." in message
        assert '    "pipeline_a" = { path = "../cat/pipelines/pipeline_a" }' in message

    def test_a_dependency_that_has_not_been_pinned(self, downstream, store):
        with pytest.raises(AssetNotPinnedError) as e:
            data.path("rates:treasury", project_dir=downstream)
        assert e.value.reason == "no_lockfile" and e.value.asset == "acme/rates:treasury"
        message = str(e.value)
        assert "'acme/rates:treasury' is not pinned" in message
        assert f"Run `chartbook pin` in {downstream}" in message
        assert "not to that pipeline's working directory" in message
        assert not store.root.exists()

    def test_a_dependency_added_since_the_last_pin(self, pinned, work, store):
        _write_manifest(work / "macro", {"dataframes": {"gdp": {"path": "./gdp.parquet", "docs": "d"}}})
        _write_manifest(
            pinned,
            {
                "project": {"id": "downstream"},
                "dependencies": {
                    "acme/rates": {"path": "../rates"},
                    "macro": {"path": "../macro"},
                },
            },
        )
        with pytest.raises(AssetNotPinnedError, match="does not list the dependency 'macro'") as e:
            data.path("macro:gdp", project_dir=pinned)
        assert e.value.reason == "no_lockfile"

    def test_an_asset_the_dependency_does_not_have(self, pinned):
        with pytest.raises(AssetNotPinnedError) as e:
            data.path("rates:treasuri", project_dir=pinned)
        assert e.value.reason == "not_in_lockfile"
        message = str(e.value)
        assert "had no dataframe named 'treasuri' when it was pinned" in message
        assert "Did you mean 'treasury'?" in message
        assert "are: by_year, not_built, treasury." in message
        assert "run `chartbook pin`" in message

    def test_it_looks_among_assets_of_the_kind_asked_for(self, pinned):
        with pytest.raises(AssetNotPinnedError, match="had no chart named 'treasury'") as e:
            assets.path("rates:chart/treasury", project_dir=pinned)
        assert "Its charts in" in str(e.value) and "are: curve." in str(e.value)

    def test_an_asset_that_was_not_built_when_it_was_pinned(self, pinned):
        with pytest.raises(AssetNotPinnedError) as e:
            data.path("rates:not_built", project_dir=pinned)
        assert e.value.reason == "not_built"
        assert "had not built it when it was pinned. Build it there" in str(e.value)

    def test_a_pin_whose_bytes_the_store_does_not_have(self, pinned, store):
        """A clean clone: the lockfile came with it, the store did not."""
        store.delete(HELLO)
        with pytest.raises(AssetNotPinnedError) as e:
            data.path("rates:treasury", project_dir=pinned)
        assert e.value.reason == "not_in_store"
        assert f"is pinned at {HELLO}, and the store at {store.root} does not have it" in str(e.value)
        assert "to put it back" in str(e.value)

        lock.pin(pinned, store)  # which is what it says to run
        assert data.path("rates:treasury", project_dir=pinned).read_bytes() == b"hello"

    def test_a_git_dependency_that_has_not_been_pinned(self, downstream, store):
        """Like any other: it says to pin. Nothing is fetched to resolve a reference."""
        _write_manifest(
            downstream,
            {"dependencies": {"crsp": {"git": "https://example.org/acme/crsp.git"}}},
        )
        with pytest.raises(AssetNotPinnedError, match="Run `chartbook pin`") as e:
            data.path("crsp:returns", project_dir=downstream)
        assert e.value.reason == "no_lockfile"

    def test_a_part_a_version_and_a_registry_are_still_reserved(self, pinned):
        with pytest.raises(UnsupportedReferenceError, match="not yet supported"):
            data.path("rates:treasury#dgs10", project_dir=pinned)
        with pytest.raises(UnsupportedRevisionError, match="not yet supported"):
            data.path("rates:treasury@v2", project_dir=pinned)
        with pytest.raises(UnsupportedRegistryError, match="not yet supported"):
            data.path("charthub.example/acme/rates:treasury", project_dir=pinned)

    def test_a_malformed_dependencies_table_names_the_file(self, pinned):
        _write_manifest(pinned, {"dependencies": {"rates": "../rates"}})
        with pytest.raises(ValueError) as e:
            data.path("rates:treasury", project_dir=pinned)
        assert str(pinned / "chartbook.toml") in str(e.value)


class TestCheap:
    """``path()`` runs at the top of every dodo.py: it must stay cheap."""

    def test_no_file_is_hashed_to_resolve_a_reference(self, pinned, monkeypatch):
        def never(path):
            raise AssertionError(f"hashed {path}")

        monkeypatch.setattr(hashing, "_file_hex", never)
        for reference in ("rates:treasury", "rates:by_year", "rates:model/ar1"):
            assets.path(reference, project_dir=pinned)

    def test_the_lockfile_is_read_once_while_it_is_unchanged(self, pinned, monkeypatch, store):
        reads = []
        real = lock.read_lock
        monkeypatch.setattr(lock, "read_lock", lambda path: reads.append(path) or real(path))
        resolve_module._lock_cache.clear()
        for _ in range(5):
            data.path("rates:treasury", project_dir=pinned)
        assert len(reads) == 1

        monkeypatch.undo()
        monkeypatch.setenv(config.STORE_ENV_VAR, str(store.root))
        locked = lock.read_lock(pinned)
        del locked.assets["acme/rates:by_year"]
        lock.write_lock(locked, pinned / lock.LOCK_FILE)
        with pytest.raises(AssetNotPinnedError):
            data.path("rates:by_year", project_dir=pinned)

    def test_the_other_pipeline_need_not_be_there(self, pinned, rates):
        """Nothing of it is read once it is pinned. It can be moved, or gone."""
        os.rename(rates, rates.with_name("rates_moved_away"))
        assert data.path("rates:treasury", project_dir=pinned).read_bytes() == b"hello"


class TestPathCommand:
    def _path(self, *args):
        return CliRunner().invoke(main, ["path", *map(str, args)])

    def test_it_prints_the_pinned_copys_path(self, pinned, store, monkeypatch):
        monkeypatch.chdir(pinned)
        result = self._path("rates:treasury")
        assert result.exit_code == 0, result.output
        assert result.stdout.strip() == str(store.get(HELLO) / "treasury.parquet")

    def test_kind_and_project_dir(self, pinned, work, monkeypatch):
        monkeypatch.chdir(work)
        result = self._path("rates:curve", "--kind", "chart", "--project-dir", pinned)
        assert result.exit_code == 0, result.output
        assert result.stdout.strip().endswith("curve.html")

    def test_not_pinned_is_an_error_with_nothing_on_stdout(self, downstream, store, monkeypatch):
        monkeypatch.chdir(downstream)
        result = self._path("rates:treasury")
        assert result.exit_code == 1 and result.stdout == ""
        assert "Error: 'acme/rates:treasury' is not pinned" in result.stderr
        assert "Run `chartbook pin`" in result.stderr


@pytest.fixture
def with_data(work, store):
    """Two real pipelines: ``upstream`` has a parquet file, ``reader`` depends on it."""
    upstream = create_pipeline_project(work / "upstream", pipeline_id="upstream").resolve()
    reader = create_pipeline_project(work / "reader", pipeline_id="reader").resolve()
    with open(reader / "chartbook.toml", "a") as f:
        f.write('\n[dependencies]\nupstream = { path = "../upstream" }\n')
    lock.pin(reader, store)
    return reader, upstream


class TestLoad:
    def test_another_pipelines_dataframe_is_loaded_from_its_pinned_copy(self, with_data):
        reader, upstream = with_data
        frame = data.load("upstream:dataframe_0", project_dir=reader)
        assert isinstance(frame, pl.LazyFrame)
        assert frame.collect().height == 10

    def test_this_pipelines_own_is_loaded_from_where_it_is(self, with_data):
        reader, _ = with_data
        assert data.load("dataframe_0", project_dir=reader).collect().height == 10
        assert data.load("dataframe/dataframe_0", project_dir=reader).collect().height == 10

    def test_what_is_loaded_does_not_change_until_an_update(self, with_data, store):
        reader, upstream = with_data
        source = upstream / "_data" / "upstream" / "dataframe_0.parquet"
        pl.DataFrame({"date": ["2026-01-01"], "value": [1.0]}).write_parquet(source)

        assert data.load("upstream:dataframe_0", project_dir=reader).collect().height == 10
        lock.update(reader, store=store)
        assert data.load("upstream:dataframe_0", project_dir=reader).collect().height == 1

    @pytest.mark.parametrize(
        "format, kind", [("polars", "LazyFrame"), ("polars_eager", "DataFrame"), ("pandas", "DataFrame")]
    )
    def test_every_format(self, with_data, format, kind):
        reader, _ = with_data
        frame = data.load("upstream:dataframe_0", format=format, project_dir=reader)
        assert type(frame).__name__ == kind
        assert data.load("upstream:dataframe_0", None, format, project_dir=reader) is not None

    def test_it_is_found_from_the_working_directory(self, with_data, monkeypatch):
        reader, _ = with_data
        monkeypatch.chdir(reader)
        assert data.load("upstream:dataframe_0").collect().height == 10

    def test_through_a_catalog_is_as_it_was(self, catalog_project):
        by_keyword = data.load(
            pipeline="pipeline_a", dataframe="dataframe_0", catalog_path=catalog_project
        )
        positional = data.load("pipeline_a", "dataframe_0", "polars", catalog_project)
        mixed = data.load("pipeline_a", dataframe="dataframe_0", catalog_path=catalog_project)
        for frame in (by_keyword, positional, mixed):
            assert frame.collect().height == 10
        with pytest.raises(KeyError, match="not_a_pipeline"):
            data.load("not_a_pipeline", "dataframe_0", catalog_path=catalog_project)

    def test_only_dataframes_are_loaded(self, with_data):
        reader, _ = with_data
        with pytest.raises(KindMismatchError, match="data.load\\(\\) loads dataframes only"):
            data.load("upstream:chart/chart_0_0", project_dir=reader)

    def test_an_undeclared_pipeline_says_what_to_add(self, with_data):
        reader, _ = with_data
        with pytest.raises(DependencyNotDeclaredError, match="\\$ chartbook pin"):
            data.load("macro:gdp", project_dir=reader)

    @pytest.mark.parametrize(
        "arguments, message",
        [
            ({}, "needs a reference to a dataframe"),
            ({"ref": "a:b", "pipeline": "a", "dataframe": "b"}, "a reference and a pipeline"),
            ({"pipeline": "a"}, "needs both a pipeline and a dataframe"),
            ({"dataframe": "b"}, "needs both a pipeline and a dataframe"),
            ({"ref": "a:b", "catalog_path": "/c"}, "catalog_path goes with"),
        ],
    )
    def test_arguments_that_are_neither_form(self, arguments, message):
        with pytest.raises(TypeError, match=message):
            data.load(**arguments)


class TestInTheIndex:
    def _add_model(self, directory: Path, trained_on: list) -> None:
        (directory / "_models").mkdir(exist_ok=True)
        (directory / "_models" / "m.json").write_text("{}")
        with open(directory / "chartbook.toml", "a") as f:
            f.write("\n" + tomli_w.dumps({"models": {"m": {"path": "./_models/m.json", "trained_on": trained_on}}}))

    def _record(self, built, kind, suffix=""):
        (record,) = [r for r in built["records"] if r["kind"] == kind and r["id"].endswith(suffix)]
        return record

    def test_a_models_record_names_the_bytes_its_inputs_are_pinned_at(self, with_data):
        reader, upstream = with_data
        self._add_model(reader, ["dataframe_0", "upstream:dataframe_0"])
        pinned_at = lock.read_lock(reader).assets["upstream:dataframe_0"]["content_hash"]
        assert pinned_at == hashing.hash_file(
            upstream / "_data" / "upstream" / "dataframe_0.parquet"
        ).content_hash

        model = self._record(index.build_index(load_manifest(reader)), "Model")
        assert model["inputs"] == ["reader:dataframe_0", "upstream:dataframe_0"]
        # Only what is another pipeline's, and so pinned, is in it
        assert model["pinned_inputs"] == {"upstream:dataframe_0": pinned_at}
        keys = list(model)
        assert keys.index("inputs") < keys.index("pinned_inputs")

    def test_it_stays_what_was_pinned_when_the_upstream_moves_on(self, with_data, store):
        reader, upstream = with_data
        self._add_model(reader, ["upstream:dataframe_0"])
        before = self._record(index.build_index(load_manifest(reader)), "Model")
        source = upstream / "_data" / "upstream" / "dataframe_0.parquet"
        pl.DataFrame({"date": ["2026-01-01"], "value": [1.0]}).write_parquet(source)

        unchanged = self._record(index.build_index(load_manifest(reader)), "Model")
        assert unchanged["pinned_inputs"] == before["pinned_inputs"]
        lock.update(reader, store=store)
        moved = self._record(index.build_index(load_manifest(reader)), "Model")
        assert moved["pinned_inputs"] == {
            "upstream:dataframe_0": hashing.hash_file(source).content_hash
        }

    def test_a_dependency_has_its_pinned_hash(self, with_data):
        reader, _ = with_data
        pipeline = self._record(index.build_index(load_manifest(reader)), "Pipeline")
        (dependency,) = pipeline["dependencies"]
        assert dependency["pinned_hash"] == lock.read_lock(reader).dependencies[0]["pinned_hash"]
        public = index.published(index.build_index(load_manifest(reader)))
        assert self._record(public, "Pipeline")["dependencies"][0]["pinned_hash"] == (
            dependency["pinned_hash"]
        )

    def test_nothing_is_said_of_what_is_not_pinned(self, with_data):
        reader, _ = with_data
        self._add_model(reader, ["upstream:dataframe_0"])
        (reader / lock.LOCK_FILE).unlink()
        built = index.build_index(load_manifest(reader))
        assert "pinned_inputs" not in self._record(built, "Model")
        assert "pinned_hash" not in self._record(built, "Pipeline")["dependencies"][0]

    def test_in_a_catalog_it_is_keyed_by_the_catalogs_id(self, work, store):
        catalog = create_catalog_project(work / "cat").resolve()
        manifest_path = catalog / "chartbook.toml"
        manifest_path.write_text(
            manifest_path.read_text()
            .replace("[pipelines.pipeline_a]", '[pipelines."acme/pipeline_a"]')
            .replace("[pipelines.pipeline_b]", '[pipelines."acme/pipeline_b"]')
        )
        pipeline_a = catalog / "pipelines" / "pipeline_a"
        with open(pipeline_a / "chartbook.toml", "a") as f:
            f.write('\n[dependencies]\nup = { path = "../pipeline_b" }\n')
        self._add_model(pipeline_a, ["up:dataframe_0"])
        lock.pin(pipeline_a, store)

        model = self._record(index.build_index(load_manifest(catalog)), "Model")
        assert model["inputs"] == ["acme/pipeline_b:dataframe_0"]
        assert list(model["pinned_inputs"]) == ["acme/pipeline_b:dataframe_0"]

    def test_the_record_fits_its_schema(self, with_data):
        reader, _ = with_data
        self._add_model(reader, ["upstream:dataframe_0"])
        built = index.build_index(load_manifest(reader))
        for kind in ("Model", "Pipeline"):
            schema = json.loads(index.schema_path(kind).read_text())
            jsonschema.validate(self._record(built, kind), schema)
        model = json.loads(index.schema_path("Model").read_text())
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {**self._record(built, "Model"), "pinned_inputs": {"x:y": "not a hash"}}, model
            )

    def test_a_lockfile_that_cannot_be_read_does_not_stop_a_build(self, with_data):
        reader, _ = with_data
        self._add_model(reader, ["upstream:dataframe_0"])
        (reader / lock.LOCK_FILE).write_text("not json")
        with pytest.warns(UserWarning, match="What is pinned is left out of the index"):
            built = index.build_index(load_manifest(reader))
        assert "pinned_inputs" not in self._record(built, "Model")

    def test_a_build_publishes_it(self, with_data, monkeypatch):
        reader, _ = with_data
        self._add_model(reader, ["upstream:dataframe_0"])
        monkeypatch.chdir(reader)
        result = CliRunner().invoke(main, ["build", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        built = json.loads((reader / "docs" / "index.json").read_text())
        pinned_at = lock.read_lock(reader).assets["upstream:dataframe_0"]["content_hash"]
        assert self._record(built, "Model")["pinned_inputs"] == {
            "upstream:dataframe_0": pinned_at
        }
