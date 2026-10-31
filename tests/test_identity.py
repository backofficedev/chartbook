"""Tests for reserved pipeline-ID syntax: the registry prefix, and the verb
that will one day push to a registry."""

import click
import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook import data
from chartbook.cli import main
from chartbook.identity import (
    UnsupportedRegistryError,
    UnsupportedRevisionError,
    derive_pipeline_id,
    looks_like_registry,
    normalize_ref_to_id,
    resolve_pipeline_ref,
    split_registry,
    validate_pipeline_id,
)
from chartbook.manifest import load_manifest

REGISTRY_IDS = [
    "charthub.example/acme/rates",
    "registry.internal.bank.org/acme/rates",
    "localhost/acme/rates",
    "localhost:5000/acme/rates",
]


class TestLooksLikeRegistry:
    @pytest.mark.parametrize(
        "component",
        ["charthub.example", "registry.internal.bank.org", "localhost", "localhost:5000"],
    )
    def test_hosts(self, component):
        assert looks_like_registry(component)

    @pytest.mark.parametrize("component", ["acme", "ftsfr", "local-host", "my_scope"])
    def test_scopes(self, component):
        assert not looks_like_registry(component)


class TestSplitRegistry:
    def test_fully_qualified(self):
        assert split_registry("charthub.example/acme/rates") == (
            "charthub.example",
            "acme/rates",
        )
        assert split_registry("localhost:5000/acme/rates") == (
            "localhost:5000",
            "acme/rates",
        )

    def test_asset_suffix_does_not_affect_the_split(self):
        assert split_registry("charthub.example/acme/rates:treasury") == (
            "charthub.example",
            "acme/rates:treasury",
        )

    @pytest.mark.parametrize("pipeline_id", ["rates", "acme/rates", "acme/rates:asset"])
    def test_unqualified_ids_have_no_registry(self, pipeline_id):
        assert split_registry(pipeline_id) == (None, pipeline_id)

    def test_dotted_scope_stays_a_scope(self):
        """Two components are always scope/name, even when the scope has a dot."""
        assert split_registry("my.group/rates") == (None, "my.group/rates")

    def test_three_components_without_a_host_is_not_a_registry(self):
        assert split_registry("a/b/c") == (None, "a/b/c")

    def test_four_components_is_not_a_registry(self):
        assert split_registry("charthub.example/a/b/c") == (
            None,
            "charthub.example/a/b/c",
        )


class TestRegistryPrefixIsReserved:
    @pytest.mark.parametrize("pipeline_id", REGISTRY_IDS)
    def test_validate_refuses_with_not_yet_supported(self, pipeline_id):
        with pytest.raises(UnsupportedRegistryError, match="not yet supported") as e:
            validate_pipeline_id(pipeline_id)
        registry = pipeline_id.split("/")[0]
        assert repr(registry) in str(e.value)
        assert "reserved syntax" in str(e.value)
        assert "use 'acme/rates' instead" in str(e.value)

    def test_it_is_a_value_error_like_the_revision_error(self):
        assert issubclass(UnsupportedRegistryError, ValueError)
        assert issubclass(UnsupportedRevisionError, ValueError)

    @pytest.mark.parametrize("pipeline_id", REGISTRY_IDS)
    def test_references_are_refused_too(self, pipeline_id):
        with pytest.raises(UnsupportedRegistryError, match="not yet supported"):
            normalize_ref_to_id(pipeline_id)
        with pytest.raises(UnsupportedRegistryError):
            resolve_pipeline_ref(["acme/rates"], pipeline_id)

    def test_host_qualified_repo_path_is_recognized_as_a_registry(self):
        """Go-style `host/owner/repo` never becomes identity; say why."""
        with pytest.raises(UnsupportedRegistryError) as e:
            normalize_ref_to_id("github.com/ftsfr/crsp_treasury")
        assert "'github.com'" in str(e.value)
        assert "'ftsfr/crsp_treasury'" in str(e.value)

    def test_revision_is_reported_before_registry(self):
        with pytest.raises(UnsupportedRevisionError):
            normalize_ref_to_id("charthub.example/acme/rates@a1b2c3d")

    def test_malformed_three_part_id_is_still_a_grammar_error(self):
        with pytest.raises(ValueError, match="Invalid pipeline id") as e:
            validate_pipeline_id("a/b/c")
        assert not isinstance(e.value, UnsupportedRegistryError)

    def test_too_many_components_is_still_a_grammar_error(self):
        with pytest.raises(ValueError, match="Invalid pipeline id") as e:
            validate_pipeline_id("charthub.example/a/b/c")
        assert not isinstance(e.value, UnsupportedRegistryError)


class TestExistingIdsAreUntouched:
    @pytest.mark.parametrize(
        "pipeline_id",
        ["rates", "acme/rates", "ftsfr/crsp_treasury", "my.group/rates", "acme/rates.v2", "localhost"],
    )
    def test_still_valid(self, pipeline_id):
        assert validate_pipeline_id(pipeline_id) == pipeline_id
        assert normalize_ref_to_id(pipeline_id) == pipeline_id

    def test_urls_still_normalize_with_the_host_dropped(self):
        assert normalize_ref_to_id("https://charthub.example/acme/rates") == "acme/rates"
        assert normalize_ref_to_id("https://gitlab.internal/grp/sub/rates.git") == "sub/rates"
        assert normalize_ref_to_id("git@github.com:acme/rates.git") == "acme/rates"

    def test_derivation_from_a_remote_is_unchanged(self, tmp_path):
        project_dir = tmp_path / "rates"
        project_dir.mkdir()
        project = {"repo_url": "https://charthub.example/acme/whatever"}
        assert derive_pipeline_id(project, project_dir) == "acme/rates"


class TestWhereIdsEnterTheSystem:
    def test_explicit_project_id(self, pipeline_project):
        toml_path = pipeline_project / "chartbook.toml"
        config = tomli.loads(toml_path.read_text(encoding="utf-8"))
        config["project"]["id"] = "charthub.example/acme/rates"
        toml_path.write_bytes(tomli_w.dumps(config).encode())
        with pytest.raises(UnsupportedRegistryError, match="not yet supported"):
            load_manifest(pipeline_project)

    def test_catalog_key(self, catalog_project):
        config = tomli.loads((catalog_project / "catalog.toml").read_text(encoding="utf-8"))
        config["pipelines"] = {"charthub.example/acme/rates": {"disabled": True}}
        (catalog_project / "catalog.toml").write_text(tomli_w.dumps(config), encoding="utf-8", newline="\n")
        with pytest.raises(UnsupportedRegistryError):
            load_manifest(catalog_project)

    def test_data_load(self, catalog_project):
        with pytest.raises(UnsupportedRegistryError, match="not yet supported"):
            data.load(
                pipeline="charthub.example/acme/rates",
                dataframe="dataframe_0",
                catalog_path=catalog_project,
            )

    def test_data_path_names_the_registry(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        with pytest.raises(UnsupportedRegistryError, match="'charthub.example'"):
            data.path("charthub.example/acme/rates:dataframe_0")

    def test_cli_reports_it_cleanly(self, catalog_project):
        result = CliRunner().invoke(
            main,
            [
                "data", "get-path",
                "--pipeline", "charthub.example/acme/rates",
                "--dataframe", "dataframe_0",
                "--catalog", str(catalog_project),
            ],
        )
        assert result.exit_code == 1
        assert "not yet supported" in result.output
        assert "Traceback" not in result.output

    def test_no_network_is_touched(self, monkeypatch):
        """Recognizing a registry is pure string work."""
        import socket

        def no_network(*args, **kwargs):
            raise AssertionError("registry syntax must not open a connection")

        monkeypatch.setattr(socket, "socket", no_network)
        monkeypatch.setattr(socket, "getaddrinfo", no_network)
        with pytest.raises(UnsupportedRegistryError):
            validate_pipeline_id("charthub.example/acme/rates")


class TestPublishIsNotOverloaded:
    """`publish` stages files to a directory. Pushing to a registry is `push`."""

    def test_publish_takes_only_local_options(self):
        publish = main.commands["publish"]
        assert {p.name for p in publish.params} == {
            "publish_dir",
            "project_dir",
            "verbose",
        }

    def test_publish_help_describes_staging_to_a_directory(self):
        result = CliRunner().invoke(main, ["publish", "--help"])
        assert result.exit_code == 0
        assert "Stage a pipeline's publishable files into a directory" in result.output
        assert "chartbook push" in result.output

    def test_push_is_a_separate_reserved_command(self):
        assert "push" in main.commands
        assert main.commands["push"] is not main.commands["publish"]
        assert main.commands["push"].params == []

    def test_push_refuses_and_points_at_publish(self):
        result = CliRunner().invoke(main, ["push"])
        assert result.exit_code == 1
        assert "reserved" in result.output
        assert "not yet supported" in result.output
        assert "chartbook publish" in result.output

    def test_push_is_not_advertised(self):
        result = CliRunner().invoke(main, ["--help"])
        listed = main.list_commands(click.Context(main))
        assert "push" in listed
        assert "\n  push " not in result.output
        assert "\n  publish " in result.output


class TestDerivedNameFromARelativePath:
    def test_dot_takes_the_name_of_the_directory_it_refers_to(self, tmp_path, monkeypatch):
        """Path('.') has no name of its own; the ID used to come out as 'pipeline'."""
        project_dir = tmp_path / "term_premium"
        project_dir.mkdir()
        (project_dir / "chartbook.toml").write_text("", encoding="utf-8", newline="\n")
        monkeypatch.chdir(project_dir)

        from pathlib import Path

        assert derive_pipeline_id({}, Path(".")) == "term_premium"
        assert load_manifest(Path("."))["project"]["id"] == "term_premium"
        assert load_manifest(".")["project"]["id"] == "term_premium"


class TestADriveLetterIsNotAHost:
    """Found by a reviewer: a Windows remote `C:\\repos\\rates` read as the scp form
    with the host `C`, so `repo_url` became `https://c/\\repos\\rates` and a page
    linked it. Git reads a one-letter "host" before the colon as a drive."""

    @pytest.mark.parametrize("remote", [r"C:\Users\me\repo", r"D:\repo.git", "c:/x", "C:/repos/rates", "Z:\\"])
    def test_a_path_with_a_drive_letter_names_no_host(self, remote):
        from chartbook.identity import id_from_address, remote_to_web_url, repository_key

        assert remote_to_web_url(remote) == ""
        assert repository_key(remote) == ""
        assert id_from_address(remote) is None

    def test_a_manifest_with_such_a_remote_has_no_repository_link(self, tmp_path, monkeypatch):
        from chartbook import manifest as manifests

        monkeypatch.setattr(manifests, "get_git_remote_url", lambda base_dir: r"C:\Users\me\repo")
        project = tmp_path / "rates"
        project.mkdir()
        (project / "chartbook.toml").write_text("", encoding="utf-8", newline="\n")
        loaded = load_manifest(project)
        assert loaded["project"]["repo_url"] == ""
        assert loaded["project"]["id"] == "rates"

    @pytest.mark.parametrize("spelling", ["Repo.git", "Repo.GIT", "Repo.Git"])
    def test_a_git_suffix_in_any_case_is_not_part_of_the_name(self, spelling):
        """`.git` was stripped case-sensitively for the web address and case-insensitively for the key,
        so `Repo.GIT` gave the ID `org/repo.git` and one repository had two IDs by spelling."""
        from chartbook.identity import id_from_address, remote_to_web_url, repository_key

        assert remote_to_web_url(f"https://github.com/Org/{spelling}") == "https://github.com/Org/Repo"
        assert remote_to_web_url(f"git@github.com:Org/{spelling}") == "https://github.com/Org/Repo"
        assert repository_key(f"https://github.com/Org/{spelling}") == "https://github.com/org/repo"
        assert id_from_address(f"git@github.com:Org/{spelling}") == "org/repo"
        assert normalize_ref_to_id(f"https://github.com/Org/{spelling}") == "Org/Repo"
