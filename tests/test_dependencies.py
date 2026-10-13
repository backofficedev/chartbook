"""Tests for declared dependencies: ``[dependencies]``, the resolution chain,
``dependencies`` in the index, and what ``check`` says about them.

This is the first part of step 3 of ``docs_src/design/overview.md``: a
pipeline says which pipelines it depends on and where each one is. Nothing
is fetched, copied or pinned, and a reference to another pipeline's asset
still does not resolve to a path.
"""

import json
import re
from pathlib import Path

import jsonschema
import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook import data, index
from chartbook.check import check_dependencies, run_checks
from chartbook.cli import main
from chartbook.diagnostics import DEFAULT_REQUIRED_FIELDS
from chartbook.identity import (
    UnsupportedRegistryError,
    UnsupportedRevisionError,
    match_pipeline_ref,
    strip_url_credentials,
)
from chartbook.manifest import (
    get_pipeline_dirs,
    load_manifest,
    resolve_project_type,
    validate_dependencies,
)
from chartbook.errors import AssetNotPinnedError
from chartbook.resolve import (
    PipelineLocation,
    PipelineNotFoundError,
    known_as,
    locate_in_catalog,
    locate_pipeline,
)
from tests.fixtures import create_catalog_project, create_pipeline_project


def _edit_toml(project_dir: Path, edit) -> None:
    """Load a project's chartbook.toml, apply ``edit(config)``, write it back."""
    toml_path = Path(project_dir) / "chartbook.toml"
    config = tomli.loads(toml_path.read_text())
    edit(config)
    toml_path.write_text(tomli_w.dumps(config))


def _depend(project_dir: Path, **dependencies) -> None:
    """Set a pipeline's ``[dependencies]``. A ``/`` in a key is written ``__``."""
    table = {key.replace("__", "/"): entry for key, entry in dependencies.items()}
    _edit_toml(project_dir, lambda config: config.update(dependencies=table))


def _add_model(project_dir: Path, trained_on: list) -> None:
    """Give a pipeline one model, trained on the given references."""
    (project_dir / "_models").mkdir(exist_ok=True)
    (project_dir / "_models" / "m.json").write_text("{}")
    _edit_toml(
        project_dir,
        lambda config: config.update(
            models={"m": {"path": "./_models/m.json", "trained_on": trained_on}}
        ),
    )


def _page_text(path: Path) -> str:
    """A built page as running text: tags removed, whitespace collapsed."""
    text = re.sub(r"<[^>]+>", " ", path.read_text())
    return re.sub(r"\s+", " ", text)


@pytest.fixture
def two_pipelines(tmp_path):
    """``downstream`` and ``rates``, side by side, as resolved paths.

    ``rates`` declares ``dataframe_0``. Neither knows about the other yet.
    """
    downstream = create_pipeline_project(tmp_path / "downstream", pipeline_id="downstream")
    rates = create_pipeline_project(tmp_path / "rates", pipeline_id="rates")
    return downstream.resolve(), rates.resolve()


class TestDeclaring:
    """What a ``[dependencies]`` table may say, and what the loader makes of it."""

    def test_a_path_dependency(self, two_pipelines):
        downstream, rates = two_pipelines
        _depend(downstream, acme__rates={"path": "../rates"})
        dependencies = load_manifest(downstream)["dependencies"]
        assert list(dependencies) == ["acme/rates"]
        assert dependencies["acme/rates"]["path"] == "../rates"
        assert dependencies["acme/rates"]["_resolved_path"] == rates

    def test_a_git_dependency(self, two_pipelines):
        downstream, _ = two_pipelines
        _depend(
            downstream,
            acme__rates={"git": "https://example.org/acme/rates", "rev": "a1b2c3d"},
            crsp={"git": "git@example.org:acme/crsp.git"},
        )
        dependencies = load_manifest(downstream)["dependencies"]
        assert dependencies["acme/rates"] == {
            "git": "https://example.org/acme/rates",
            "rev": "a1b2c3d",
        }
        assert dependencies["crsp"] == {"git": "git@example.org:acme/crsp.git"}

    def test_no_table_means_no_key(self, two_pipelines):
        downstream, _ = two_pipelines
        assert "dependencies" not in load_manifest(downstream)

    def test_an_empty_table_is_kept(self, two_pipelines):
        downstream, _ = two_pipelines
        _depend(downstream)
        assert load_manifest(downstream)["dependencies"] == {}

    def test_the_directory_need_not_be_there_to_load(self, two_pipelines):
        """A manifest loads on a machine that does not have the dependency."""
        downstream, _ = two_pipelines
        _depend(downstream, rates={"path": "../not_cloned_yet"})
        entry = load_manifest(downstream)["dependencies"]["rates"]
        assert entry["_resolved_path"] == downstream.parent / "not_cloned_yet"

    def test_an_absolute_path(self, two_pipelines):
        downstream, rates = two_pipelines
        _depend(downstream, rates={"path": str(rates)})
        assert load_manifest(downstream)["dependencies"]["rates"]["_resolved_path"] == rates

    def test_a_manifest_with_only_dependencies_is_a_pipeline(self):
        raw = {"dependencies": {"rates": {"path": "../rates"}}}
        assert resolve_project_type(raw) == "pipeline"

    def test_the_raw_table_is_left_alone(self, tmp_path):
        raw = {"rates": {"path": "../rates"}}
        validated = validate_dependencies(raw, tmp_path)
        assert "_resolved_path" in validated["rates"]
        assert raw == {"rates": {"path": "../rates"}}

    @pytest.mark.parametrize(
        "table, message",
        [
            ("../rates", "must be a table with one entry per pipeline"),
            ({"rates": "../rates"}, "must be a table that says where the pipeline is"),
            ({"rates": {}}, "does not say where the pipeline is"),
            ({"rates": {"path": "../rates", "git": "https://x/y"}}, "both 'path' and 'git'"),
            ({"rates": {"path": "../rates", "rev": "v1"}}, "'rev' beside a 'path'"),
            ({"rates": {"path": ""}}, "'path' must be a non-empty string"),
            ({"rates": {"path": {"unix": "../rates"}}}, "'path' must be a non-empty string"),
            ({"rates": {"git": 3}}, "'git' must be a non-empty string"),
            ({"rates": {"git": "https://x/y", "rev": 7}}, "'rev' must be a non-empty string"),
            ({"a/b/c": {"path": "../rates"}}, "Invalid pipeline id"),
            ({"my rates": {"path": "../rates"}}, "Invalid pipeline id"),
        ],
    )
    def test_a_malformed_table_is_refused(self, tmp_path, table, message):
        with pytest.raises(ValueError, match=re.escape(message)):
            validate_dependencies(table, tmp_path)

    def test_a_rev_alone_says_the_repository_cannot_be_worked_out(self, tmp_path):
        with pytest.raises(ValueError) as e:
            validate_dependencies({"acme/rates": {"rev": "a1b2c3d"}}, tmp_path)
        assert "does not say where the pipeline is" in str(e.value)
        assert "a 'rev' needs a 'git' beside it" in str(e.value)

    def test_an_unknown_key_suggests_the_one_meant(self, tmp_path):
        with pytest.raises(ValueError) as e:
            validate_dependencies({"rates": {"paht": "../rates"}}, tmp_path)
        assert "unknown key 'paht'" in str(e.value)
        assert "path, git, rev" in str(e.value)
        assert "Did you mean 'path'?" in str(e.value)

    def test_an_unquoted_dotted_key_is_explained(self, tmp_path):
        """``my.group = {...}`` is TOML for a table inside a table."""
        table = tomli.loads('[dependencies]\nacme.rates = { path = "../rates" }')
        with pytest.raises(ValueError) as e:
            validate_dependencies(table["dependencies"], tmp_path)
        assert "must be quoted" in str(e.value)
        assert '"acme/rates" = { path = "..." }' in str(e.value)

    def test_a_revision_in_a_key_is_reserved(self, tmp_path):
        with pytest.raises(UnsupportedRevisionError) as e:
            validate_dependencies({"acme/rates@v2": {"path": "../rates"}}, tmp_path)
        assert "reserved syntax and not yet supported" in str(e.value)
        assert "use 'acme/rates' as the key" in str(e.value)

    def test_a_registry_in_a_key_is_reserved(self, tmp_path):
        key = "charthub.example/acme/rates"
        with pytest.raises(UnsupportedRegistryError, match="not yet supported"):
            validate_dependencies({key: {"path": "../rates"}}, tmp_path)

    def test_an_error_names_the_file(self, two_pipelines):
        downstream, _ = two_pipelines
        _depend(downstream, rates={"path": "../rates", "git": "https://x/y"})
        with pytest.raises(ValueError) as e:
            load_manifest(downstream)
        assert str(downstream / "chartbook.toml") in str(e.value)
        assert "[dependencies]: 'rates'" in str(e.value)

    def test_a_reserved_key_stays_a_not_yet_error_through_the_loader(self, two_pipelines):
        downstream, _ = two_pipelines
        _depend(downstream, **{"rates@v2": {"path": "../rates"}})
        with pytest.raises(UnsupportedRevisionError, match="not yet supported"):
            load_manifest(downstream)

    def test_a_catalog_has_no_dependencies(self, tmp_path):
        catalog = create_catalog_project(tmp_path / "cat")
        _depend(catalog, rates={"path": "../rates"})
        with pytest.raises(ValueError, match=r"a catalog has no \[dependencies\]"):
            load_manifest(catalog)


class TestStrippingCredentials:
    @pytest.mark.parametrize(
        "declared, shown",
        [
            ("https://user:token@example.org/acme/x.git", "https://example.org/acme/x.git"),
            ("https://token@example.org/acme/x", "https://example.org/acme/x"),
            ("HTTPS://token@example.org/acme/x", "HTTPS://example.org/acme/x"),
            ("https://example.org/acme/x@v2", "https://example.org/acme/x@v2"),
            ("ssh://git@example.org/acme/x.git", "ssh://git@example.org/acme/x.git"),
            ("ssh://git:secret@example.org:2222/acme/x", "ssh://git@example.org:2222/acme/x"),
            ("git@example.org:acme/x.git", "git@example.org:acme/x.git"),
            ("/srv/git/x.git", "/srv/git/x.git"),
            ("../x", "../x"),
        ],
    )
    def test_a_url_is_shown_without_them(self, declared, shown):
        assert strip_url_credentials(declared) == shown


class TestMatchingAName:
    def test_nothing_matching_is_none(self):
        assert match_pipeline_ref(["acme/rates"], "nope") is None
        assert match_pipeline_ref([], "nope") is None

    def test_an_ambiguous_name_says_where(self):
        with pytest.raises(KeyError, match=r"ambiguous in \[dependencies\]"):
            match_pipeline_ref(["a/rates", "b/rates"], "rates", where="[dependencies]")


class TestTheChain:
    """``locate_pipeline``: dependencies, then the catalog, then an error."""

    DEPENDENCIES = {
        "acme/rates": {"path": "../rates", "_resolved_path": Path("/work/rates")},
        "acme/crsp": {"git": "https://example.org/acme/crsp", "rev": "a1b2c3d"},
    }
    CATALOG = {
        "acme/rates": Path("/catalog/rates"),
        "ftsfr/macro": Path("/catalog/macro"),
    }

    def test_a_declared_dependency_is_found_first(self):
        location = locate_pipeline(
            "acme/rates", dependencies=self.DEPENDENCIES, catalog=self.CATALOG
        )
        assert location == PipelineLocation(
            id="acme/rates",
            found_in="dependencies",
            kind="path",
            path=Path("/work/rates"),
        )

    def test_then_the_catalog(self):
        location = locate_pipeline(
            "ftsfr/macro", dependencies=self.DEPENDENCIES, catalog=self.CATALOG
        )
        assert location == PipelineLocation(
            id="ftsfr/macro",
            found_in="catalog",
            kind="path",
            path=Path("/catalog/macro"),
        )

    def test_a_git_dependency_has_no_path(self):
        location = locate_pipeline("acme/crsp", dependencies=self.DEPENDENCIES)
        assert location == PipelineLocation(
            id="acme/crsp",
            found_in="dependencies",
            kind="git",
            url="https://example.org/acme/crsp",
            rev="a1b2c3d",
        )

    @pytest.mark.parametrize(
        "reference", ["rates", "acme/rates", "https://example.org/acme/rates.git"]
    )
    def test_a_name_is_matched_as_a_catalog_matches_one(self, reference):
        location = locate_pipeline(reference, dependencies=self.DEPENDENCIES)
        assert location.id == "acme/rates"

    def test_a_scoped_name_must_match_exactly(self):
        """``other/rates`` is not ``acme/rates``, whatever step is asked."""
        with pytest.raises(PipelineNotFoundError):
            locate_pipeline(
                "other/rates", dependencies=self.DEPENDENCIES, catalog=self.CATALOG
            )

    def test_an_ambiguous_dependency_does_not_fall_through_to_the_catalog(self):
        dependencies = {
            "a/macro": {"path": "../a", "_resolved_path": Path("/a")},
            "b/macro": {"path": "../b", "_resolved_path": Path("/b")},
        }
        with pytest.raises(KeyError, match=r"ambiguous in \[dependencies\]") as e:
            locate_pipeline("macro", dependencies=dependencies, catalog=self.CATALOG)
        assert not isinstance(e.value, PipelineNotFoundError)

    def test_not_found_lists_the_candidates(self):
        with pytest.raises(PipelineNotFoundError) as e:
            locate_pipeline("rate", dependencies=self.DEPENDENCIES, catalog=self.CATALOG)
        message = str(e.value)
        assert message.startswith("Pipeline 'rate' not found.")
        assert "Declared in [dependencies]: acme/crsp, acme/rates." in message
        assert "In the catalog: acme/rates, ftsfr/macro." in message
        assert e.value.pipeline == "rate"
        assert e.value.candidates == {
            "dependencies": ["acme/crsp", "acme/rates"],
            "catalog": ["acme/rates", "ftsfr/macro"],
        }

    def test_not_found_suggests_a_close_name(self):
        with pytest.raises(PipelineNotFoundError, match="Did you mean 'ftsfr/macro'"):
            locate_pipeline("ftsfr/macr", catalog=self.CATALOG)

    def test_not_found_is_a_key_error_that_reads_as_a_sentence(self):
        with pytest.raises(KeyError) as e:
            locate_pipeline("nope")
        assert str(e.value) == "Pipeline 'nope' not found."

    def test_not_found_names_only_the_steps_that_were_asked(self):
        with pytest.raises(PipelineNotFoundError) as e:
            locate_pipeline("nope", dependencies={})
        assert str(e.value) == (
            "Pipeline 'nope' not found. Declared in [dependencies]: (none)."
        )
        assert e.value.candidates == {"dependencies": []}
        with pytest.raises(PipelineNotFoundError) as e:
            locate_pipeline("nope", catalog=self.CATALOG)
        assert "[dependencies]" not in str(e.value)
        assert "In the catalog: acme/rates, ftsfr/macro." in str(e.value)

    def test_a_registry_is_still_reserved(self):
        """Step three of the chain is a hole, and says so."""
        with pytest.raises(UnsupportedRegistryError, match="not yet supported"):
            locate_pipeline("charthub.example/acme/rates", catalog=self.CATALOG)

    def test_a_revision_is_still_reserved(self):
        with pytest.raises(UnsupportedRevisionError, match="not yet supported"):
            locate_pipeline("acme/rates@v2", dependencies=self.DEPENDENCIES)

    def test_a_catalog_lookup_enters_at_the_second_step(self, catalog_project):
        manifest = load_manifest(catalog_project)
        assert locate_in_catalog(manifest, "pipeline_a") == "pipeline_a"
        with pytest.raises(PipelineNotFoundError, match="In the catalog: pipeline_a"):
            locate_in_catalog(manifest, "nope")

    def test_loading_through_a_catalog_is_unchanged(self, catalog_project):
        frame = data.load("pipeline_a", "dataframe_0", catalog_path=catalog_project)
        assert frame.collect().height > 0
        with pytest.raises(KeyError, match="not_a_pipeline"):
            data.load("not_a_pipeline", "dataframe_0", catalog_path=catalog_project)


class TestKnownAs:
    """A dependency's key is a local name; a build has its own."""

    def test_a_pipeline_of_the_build_takes_the_builds_id(self, two_pipelines):
        _, rates = two_pipelines
        location = PipelineLocation(
            id="rates", found_in="dependencies", kind="path", path=rates
        )
        assert known_as(location, {"acme/rates": rates}) == "acme/rates"

    def test_any_other_keeps_the_name_it_was_found_under(self, two_pipelines):
        downstream, rates = two_pipelines
        location = PipelineLocation(
            id="rates", found_in="dependencies", kind="path", path=rates
        )
        assert known_as(location, {"acme/downstream": downstream}) == "rates"
        assert known_as(location, {}) == "rates"

    def test_a_directory_that_is_not_there_is_compared_by_name(self, tmp_path):
        missing = tmp_path / "missing"
        location = PipelineLocation(
            id="rates", found_in="dependencies", kind="path", path=missing
        )
        assert known_as(location, {"acme/rates": missing}) == "acme/rates"
        assert known_as(location, {"acme/rates": tmp_path / "other"}) == "rates"

    def test_a_git_dependency_keeps_its_key(self):
        location = PipelineLocation(
            id="acme/crsp", found_in="dependencies", kind="git", url="https://x/y"
        )
        assert known_as(location, {"acme/crsp": Path("/somewhere")}) == "acme/crsp"


class TestTrainedOnADependency:
    """A model's training data in another pipeline should name a declared one."""

    def test_an_undeclared_pipeline_does_not_load(self, two_pipelines):
        """It was a warning until references to other pipelines resolved."""
        downstream, _ = two_pipelines
        _add_model(downstream, ["acme/rates:dataframe_0"])
        with pytest.raises(ValueError) as e:
            load_manifest(downstream)
        message = str(e.value)
        assert "[models.m]: trained_on names 'acme/rates:dataframe_0'" in message
        assert "which [dependencies] does not declare" in message
        assert '"acme/rates" = { path = "../rates" }' in message

    @pytest.mark.parametrize("reference", ["rates:dataframe_0", "acme/rates:dataframe_0"])
    def test_a_declared_pipeline_loads_quietly(self, two_pipelines, recwarn, reference):
        downstream, _ = two_pipelines
        _depend(downstream, acme__rates={"path": "../rates"})
        _add_model(downstream, [reference])
        load_manifest(downstream)
        assert not [w for w in recwarn if "[dependencies]" in str(w.message)]

    def test_this_pipelines_own_dataframe_needs_no_dependency(self, two_pipelines, recwarn):
        downstream, _ = two_pipelines
        _add_model(downstream, ["dataframe_0"])
        load_manifest(downstream)
        assert not [w for w in recwarn if "[dependencies]" in str(w.message)]

    def test_a_name_that_fits_two_dependencies_is_refused(self, two_pipelines):
        downstream, _ = two_pipelines
        _depend(downstream, a__rates={"path": "../rates"}, b__rates={"path": "../other"})
        _add_model(downstream, ["rates:dataframe_0"])
        with pytest.raises(ValueError) as e:
            load_manifest(downstream)
        assert "[models.m]: trained_on:" in str(e.value)
        assert "ambiguous in [dependencies]" in str(e.value)

    def test_declaring_is_not_pinning(self, two_pipelines):
        """Its assets resolve to pinned copies, so there has to be a pin."""
        downstream, _ = two_pipelines
        _depend(downstream, rates={"path": "../rates"})
        with pytest.raises(AssetNotPinnedError, match="Run `chartbook pin`") as e:
            data.path("rates:dataframe_0", project_dir=downstream)
        assert e.value.reason == "no_lockfile"


class TestInTheIndex:
    def _pipeline_record(self, built, pipeline_id) -> dict:
        (record,) = [
            r for r in built["records"] if r["kind"] == "Pipeline" and r["id"] == pipeline_id
        ]
        return record

    def _model_record(self, built) -> dict:
        (record,) = [r for r in built["records"] if r["kind"] == "Model"]
        return record

    def test_a_pipeline_record_lists_its_dependencies(self, two_pipelines):
        downstream, rates = two_pipelines
        _depend(
            downstream,
            zeta={"git": "https://example.org/acme/zeta", "rev": "a1b2c3d"},
            acme__rates={"path": "../rates"},
            no_rev={"git": "git@example.org:acme/no_rev.git"},
        )
        built = index.build_index(load_manifest(downstream))
        record = self._pipeline_record(built, "downstream")
        assert record["dependencies"] == [
            {
                "id": "acme/rates",
                "via": "path",
                "location": {"kind": "path", "path": "../rates", "value": rates.as_posix()},
            },
            {
                "id": "no_rev",
                "via": "rev",
                "location": {"kind": "git", "url": "git@example.org:acme/no_rev.git"},
            },
            {
                "id": "zeta",
                "via": "rev",
                "location": {
                    "kind": "git",
                    "url": "https://example.org/acme/zeta",
                    "rev": "a1b2c3d",
                },
            },
        ]
        # Between what a pipeline runs and what it has
        keys = list(record)
        assert keys.index("location") < keys.index("dependencies") < keys.index("assets")

    def test_absent_without_the_table_and_empty_with_an_empty_one(self, two_pipelines):
        downstream, _ = two_pipelines
        built = index.build_index(load_manifest(downstream))
        assert "dependencies" not in self._pipeline_record(built, "downstream")
        _depend(downstream)
        built = index.build_index(load_manifest(downstream))
        assert self._pipeline_record(built, "downstream")["dependencies"] == []

    def test_the_published_index_has_no_local_directory(self, two_pipelines):
        downstream, rates = two_pipelines
        _depend(
            downstream,
            acme__rates={"path": "../rates"},
            zeta={"git": "https://example.org/acme/zeta", "rev": "a1b2c3d"},
        )
        full = index.build_index(load_manifest(downstream))
        public = index.published(full)
        path_entry, git_entry = self._pipeline_record(public, "downstream")["dependencies"]
        assert path_entry["location"] == {"kind": "path", "path": "../rates"}
        assert git_entry["location"]["url"] == "https://example.org/acme/zeta"
        assert str(rates) not in json.dumps(public)
        # ...and the full one was not changed by publishing it
        assert "value" in self._pipeline_record(full, "downstream")["dependencies"][0]["location"]

    @pytest.mark.parametrize(
        "declared, written",
        [
            ("https://user:token@example.org/acme/x.git", "https://example.org/acme/x.git"),
            ("https://token@example.org/acme/x", "https://example.org/acme/x"),
            ("ssh://git@example.org/acme/x.git", "ssh://git@example.org/acme/x.git"),
            ("ssh://git:secret@example.org:2222/acme/x", "ssh://git@example.org:2222/acme/x"),
            ("git@example.org:acme/x.git", "git@example.org:acme/x.git"),
            ("/srv/git/x.git", "/srv/git/x.git"),
        ],
    )
    def test_credentials_in_a_git_url_do_not_reach_the_index(
        self, two_pipelines, declared, written
    ):
        downstream, _ = two_pipelines
        _depend(downstream, x={"git": declared})
        built = index.build_index(load_manifest(downstream))
        (entry,) = self._pipeline_record(built, "downstream")["dependencies"]
        assert entry["location"]["url"] == written

    def test_the_record_fits_its_schema(self, two_pipelines):
        downstream, _ = two_pipelines
        _depend(
            downstream,
            acme__rates={"path": "../rates"},
            zeta={"git": "https://example.org/acme/zeta", "rev": "a1b2c3d"},
        )
        schema = json.loads(index.schema_path("Pipeline").read_text())
        full = index.build_index(load_manifest(downstream))
        for built in (full, index.published(full)):
            record = self._pipeline_record(built, "downstream")
            jsonschema.validate(record, schema)

    def test_the_schema_refuses_a_dependency_without_a_location(self):
        schema = json.loads(index.schema_path("Pipeline").read_text())
        record = {
            "kind": "Pipeline",
            "version": "chartbook/v1",
            "id": "p",
            "name": "P",
            "location": {"kind": "path"},
            "assets": [],
            "dependencies": [{"id": "acme/rates", "via": "path"}],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(record, schema)

    def test_an_input_is_written_by_the_dependencys_name(self, two_pipelines):
        """``rates`` in a reference is the pipeline declared as ``acme/rates``."""
        downstream, _ = two_pipelines
        _depend(downstream, acme__rates={"path": "../rates"})
        _add_model(downstream, ["dataframe_0", "rates:dataframe_0"])
        built = index.build_index(load_manifest(downstream))
        assert self._model_record(built)["inputs"] == [
            "downstream:dataframe_0",
            "acme/rates:dataframe_0",
        ]

    def test_in_a_catalog_a_dependency_goes_by_the_catalogs_name(self, tmp_path):
        """One directory, two names: the build's is the one its records use."""
        catalog = create_catalog_project(tmp_path / "cat")

        def scope(config):
            for name in ("pipeline_a", "pipeline_b"):
                config["pipelines"][f"acme/{name}"] = config["pipelines"].pop(name)

        _edit_toml(catalog, scope)
        pipeline_a = catalog / "pipelines" / "pipeline_a"
        _depend(pipeline_a, upstream={"path": "../pipeline_b"})
        _add_model(pipeline_a, ["upstream:dataframe_0"])

        built = index.build_index(load_manifest(catalog))
        (dependency,) = self._pipeline_record(built, "acme/pipeline_a")["dependencies"]
        assert dependency["id"] == "acme/pipeline_b"
        assert self._model_record(built)["inputs"] == ["acme/pipeline_b:dataframe_0"]
        ids = [r.get("id") for r in built["records"]]
        assert dependency["id"] in ids and "acme/pipeline_b:dataframe_0" in ids

        # Alone, the same pipeline writes the name it declared
        alone = index.build_index(load_manifest(pipeline_a))
        (dependency,) = self._pipeline_record(alone, "pipeline_a")["dependencies"]
        assert dependency["id"] == "upstream"
        assert self._model_record(alone)["inputs"] == ["upstream:dataframe_0"]

    def test_a_build_writes_it_beside_the_site(self, two_pipelines, monkeypatch):
        downstream, _ = two_pipelines
        _depend(downstream, acme__rates={"path": "../rates"})
        _add_model(downstream, ["rates:dataframe_0"])
        monkeypatch.chdir(downstream)
        result = CliRunner().invoke(main, ["docs", "./docs", "-f"])
        assert result.exit_code == 0, result.output

        built = json.loads((downstream / "docs" / "index.json").read_text())
        (dependency,) = self._pipeline_record(built, "downstream")["dependencies"]
        assert dependency == {
            "id": "acme/rates",
            "via": "path",
            "location": {"kind": "path", "path": "../rates"},
        }
        # The page names the dataframe by the declared name, with no link:
        # the site is of this pipeline alone
        page = downstream / "docs" / "cb" / "models" / "downstream" / "m.html"
        assert "acme/rates:dataframe_0 (in another pipeline" in _page_text(page)
        assert "dataframes/acme--rates" not in page.read_text()


class TestCheck:
    def _problems(self, project) -> list:
        manifest = load_manifest(project)
        return [p for p in run_checks(manifest, project) if p.table.startswith("dependencies")]

    def test_a_dependency_that_is_there_is_no_problem(self, two_pipelines):
        downstream, _ = two_pipelines
        _depend(downstream, acme__rates={"path": "../rates"})
        assert self._problems(downstream) == []

    def test_a_directory_that_is_not_there(self, two_pipelines):
        downstream, _ = two_pipelines
        _depend(downstream, acme__rates={"path": "../not_cloned_yet"})
        (problem,) = self._problems(downstream)
        assert problem.file == downstream / "chartbook.toml"
        assert problem.table == 'dependencies."acme/rates"'
        assert problem.field == "path"
        assert problem.message == (
            f"directory not found: {downstream.parent / 'not_cloned_yet'}"
        )
        assert problem.format(relative_to=downstream) == (
            f'chartbook.toml: [dependencies."acme/rates"] path: {problem.message}'
        )

    def test_a_bare_key_is_written_bare(self, two_pipelines):
        downstream, _ = two_pipelines
        _depend(downstream, rates={"path": "../not_cloned_yet"})
        (problem,) = self._problems(downstream)
        assert problem.table == "dependencies.rates"

    def test_a_directory_with_no_manifest(self, two_pipelines):
        downstream, _ = two_pipelines
        (downstream.parent / "just_a_folder").mkdir()
        _depend(downstream, rates={"path": "../just_a_folder"})
        (problem,) = self._problems(downstream)
        assert "no chartbook.toml in" in problem.message
        assert "a dependency is a pipeline" in problem.message

    def test_a_catalog_is_not_a_pipeline(self, two_pipelines):
        downstream, _ = two_pipelines
        create_catalog_project(downstream.parent / "cat")
        _depend(downstream, cat={"path": "../cat"})
        (problem,) = self._problems(downstream)
        assert "is a catalog, not a pipeline" in problem.message

    def test_a_manifest_that_cannot_be_read(self, two_pipelines):
        downstream, rates = two_pipelines
        (rates / "chartbook.toml").write_text("[project\n")
        _depend(downstream, rates={"path": "../rates"})
        (problem,) = self._problems(downstream)
        assert problem.message.startswith(f"cannot read {rates / 'chartbook.toml'}")

    def test_an_old_format_manifest_says_so_once(self, two_pipelines):
        downstream, rates = two_pipelines
        (rates / "chartbook.toml").write_text('[config]\ntype = "pipeline"\n')
        _depend(downstream, rates={"path": "../rates"})
        (problem,) = self._problems(downstream)
        assert "old v1 format" in problem.message
        assert problem.message.count(str(rates / "chartbook.toml")) == 1

    def test_a_pipeline_cannot_depend_on_itself(self, two_pipelines):
        downstream, _ = two_pipelines
        _depend(downstream, me={"path": "."})
        (problem,) = self._problems(downstream)
        assert "cannot depend on itself" in problem.message

    def test_a_git_dependency_is_a_warning_not_a_problem(self, two_pipelines):
        downstream, _ = two_pipelines
        _depend(downstream, acme__crsp={"git": "https://example.org/acme/crsp", "rev": "v1"})
        manifest = load_manifest(downstream)
        with pytest.warns(UserWarning, match="has not been fetched here") as caught:
            assert check_dependencies(manifest, downstream) == []
        (warning,) = caught
        assert '[dependencies."acme/crsp"] git: not checked' in str(warning.message)
        assert "`chartbook pin` fetches it" in str(warning.message)

    def test_a_token_in_a_git_url_does_not_reach_the_log(self, two_pipelines, monkeypatch):
        downstream, _ = two_pipelines
        _depend(downstream, crsp={"git": "https://user:s3cret@example.org/acme/crsp.git"})
        monkeypatch.chdir(downstream)
        result = CliRunner().invoke(main, ["check"])
        assert "https://example.org/acme/crsp.git has not been fetched here" in result.output
        assert "s3cret" not in result.output

    def test_training_data_the_dependency_does_not_declare(self, two_pipelines):
        """Outside any catalog: the dependency says where to look."""
        downstream, _ = two_pipelines
        _depend(downstream, acme__rates={"path": "../rates"})
        _add_model(downstream, ["rates:no_such_table", "rates:dataframe_0"])
        (problem,) = [
            p
            for p in run_checks(load_manifest(downstream), downstream)
            if p.field == "trained_on" and "does not declare" in p.message
        ]
        assert problem.table == "models.m"
        assert "'rates:no_such_table'" in problem.message
        assert "the pipeline 'acme/rates' does not declare" in problem.message
        assert "Its dataframes are: dataframe_0" in problem.message

    def test_training_data_in_a_dependency_that_is_missing_is_reported_once(
        self, two_pipelines
    ):
        downstream, _ = two_pipelines
        _depend(downstream, rates={"path": "../not_cloned_yet"})
        _add_model(downstream, ["rates:dataframe_0"])
        problems = run_checks(load_manifest(downstream), downstream)
        assert [p.table for p in problems if "not_cloned_yet" in p.message] == [
            "dependencies.rates"
        ]
        assert not [p for p in problems if "does not declare" in p.message]

    def test_training_data_in_a_git_dependency_is_not_checked(self, two_pipelines):
        downstream, _ = two_pipelines
        _depend(downstream, rates={"git": "https://example.org/acme/rates"})
        _add_model(downstream, ["rates:anything"])
        problems = run_checks(load_manifest(downstream), downstream)
        assert not [p for p in problems if p.field == "trained_on"]

    def test_one_id_for_two_directories_in_a_catalog(self, tmp_path):
        catalog = create_catalog_project(tmp_path / "cat").resolve()
        pipeline_a = catalog / "pipelines" / "pipeline_a"
        other = create_pipeline_project(tmp_path / "other", pipeline_id="pipeline_b").resolve()
        _depend(pipeline_a, pipeline_b={"path": str(other)})
        (problem,) = self._problems(catalog)
        assert problem.file == pipeline_a / "chartbook.toml"
        assert problem.table == "dependencies.pipeline_b"
        assert "one ID for two pipelines" in problem.message
        assert str(other) in problem.message
        assert str(catalog / "pipelines" / "pipeline_b") in problem.message

        # The same directory under the same ID is what a catalog expects
        _depend(pipeline_a, pipeline_b={"path": "../pipeline_b"})
        assert self._problems(catalog) == []

        # Alone, the pipeline has nothing to collide with
        _depend(pipeline_a, pipeline_b={"path": str(other)})
        assert self._problems(pipeline_a) == []

    def test_every_pipeline_of_a_catalog_is_checked(self, tmp_path):
        catalog = create_catalog_project(tmp_path / "cat").resolve()
        _depend(catalog / "pipelines" / "pipeline_b", gone={"path": "../gone"})
        (problem,) = self._problems(catalog)
        assert problem.file == catalog / "pipelines" / "pipeline_b" / "chartbook.toml"

    def test_get_pipeline_dirs(self, tmp_path, two_pipelines):
        downstream, _ = two_pipelines
        assert get_pipeline_dirs(load_manifest(downstream)) == {"downstream": downstream}
        catalog = create_catalog_project(tmp_path / "cat").resolve()
        assert get_pipeline_dirs(load_manifest(catalog)) == {
            "pipeline_a": catalog / "pipelines" / "pipeline_a",
            "pipeline_b": catalog / "pipelines" / "pipeline_b",
        }


class TestCheckCommand:
    def _check(self, project, monkeypatch):
        """Run ``chartbook check`` in a project, against a policy that asks for nothing."""
        policy = project.parent / "policy.toml"
        required = {"required": {table: [] for table in DEFAULT_REQUIRED_FIELDS}}
        policy.write_text(tomli_w.dumps({"policy": required}))
        monkeypatch.chdir(project)
        return CliRunner().invoke(main, ["check", "--policy", str(policy)])

    def test_ok_counts_the_dependencies(self, two_pipelines, monkeypatch):
        downstream, _ = two_pipelines
        result = self._check(downstream, monkeypatch)
        assert result.exit_code == 0, result.output
        assert "dependencies" not in result.output

        _depend(downstream, acme__rates={"path": "../rates"})
        result = self._check(downstream, monkeypatch)
        assert result.exit_code == 0, result.output
        assert "0 notebooks, 1 dependencies)" in result.output

    def test_a_missing_dependency_fails(self, two_pipelines, monkeypatch):
        downstream, _ = two_pipelines
        _depend(downstream, acme__rates={"path": "../not_cloned_yet"})
        result = self._check(downstream, monkeypatch)
        assert result.exit_code == 1
        assert 'chartbook.toml: [dependencies."acme/rates"] path: directory not found' in (
            result.output
        )

    def test_an_undeclared_pipeline_fails(self, two_pipelines, monkeypatch):
        downstream, _ = two_pipelines
        _add_model(downstream, ["rates:dataframe_0"])
        result = self._check(downstream, monkeypatch)
        assert result.exit_code == 1
        assert result.output.startswith("Error: [models.m]: trained_on names")
        assert "which [dependencies] does not declare" in result.output

    def test_a_git_dependency_is_a_warning(self, two_pipelines, monkeypatch):
        downstream, _ = two_pipelines
        _depend(downstream, acme__crsp={"git": "https://example.org/acme/crsp"})
        result = self._check(downstream, monkeypatch)
        assert result.exit_code == 0, result.output
        assert "warning: " in result.output
        assert '[dependencies."acme/crsp"] git: not checked' in result.output
        assert "1 dependencies)" in result.output


class TestPages:
    def test_a_catalog_page_links_through_a_dependencys_own_name(self, tmp_path, monkeypatch):
        """``upstream`` is this pipeline's name for what the catalog calls ``acme/pipeline_b``."""
        catalog = create_catalog_project(tmp_path / "cat")

        def scope(config):
            for name in ("pipeline_a", "pipeline_b"):
                config["pipelines"][f"acme/{name}"] = config["pipelines"].pop(name)

        _edit_toml(catalog, scope)
        pipeline_a = catalog / "pipelines" / "pipeline_a"
        _depend(pipeline_a, upstream={"path": "../pipeline_b"})
        _add_model(pipeline_a, ["upstream:dataframe_0"])

        monkeypatch.chdir(catalog)
        result = CliRunner().invoke(main, ["docs", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        page = catalog / "docs" / "cb" / "models" / "acme--pipeline_a" / "m.html"
        assert 'href="../../dataframes/acme--pipeline_b/dataframe_0.html"' in page.read_text()
        assert "acme/pipeline_b:dataframe_0 - Dataframe 0" in _page_text(page)
