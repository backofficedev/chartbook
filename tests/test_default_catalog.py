"""By default a store and a catalog are one unit.

The first command that needs the catalog makes it, ``~/.chartbook/catalog.toml``,
over the store this machine uses: asked at a terminal, where Enter says yes;
made and said on stderr where nothing can ask. A catalog the settings name,
and an old one that wants ``catalog migrate``, are left as they are.
"""
import tomli
import pytest
from click.testing import CliRunner

from chartbook import cli, config, snapshot
from chartbook.cli import main
from chartbook.store import FolderStore, default_store
from tests.test_several_stores import configure, pipeline


@pytest.fixture
def stored(tmp_path):
    """A pipeline with a snapshot in the machine's (scratch) store, and no catalog yet."""
    folder = pipeline(tmp_path)
    snapshot.make(folder, default_store())
    assert not config.get_global_catalog_path().exists()
    return folder


def _made_line() -> str:
    return f"Made {config.get_global_catalog_path()}: a catalog over your store at {config.get_store_url()}."


def _stores_of(path) -> dict:
    return tomli.loads(path.read_text(encoding="utf-8"))["stores"]


class TestWhereNothingCanAsk:
    def test_ls_makes_the_catalog_and_says_so(self, stored):
        result = CliRunner().invoke(main, ["ls"])
        assert result.exit_code == 0, result.output
        made = config.get_global_catalog_path()
        assert made.is_file()
        assert _made_line() in result.output
        assert "[pipeline] acme/upstream" in result.output
        assert _stores_of(made) == {"default": {"url": config.get_store_url()}}
        # Once: the next command finds it and says nothing
        again = CliRunner().invoke(main, ["ls"])
        assert again.exit_code == 0, again.output
        assert "Made " not in again.output

    def test_get_docs_makes_it(self, stored):
        result = CliRunner().invoke(main, ["get-docs", "acme/upstream"])
        assert result.exit_code == 0, result.output
        assert config.get_global_catalog_path().is_file()
        assert _made_line() in result.output

    def test_catalog_open_makes_it_and_says_to_build(self, stored):
        result = CliRunner().invoke(main, ["catalog", "open"])
        assert result.exit_code == 1
        assert config.get_global_catalog_path().is_file()
        assert _made_line() in result.output
        assert "Run 'chartbook catalog build' first." in result.output

    def test_snapshot_makes_it_after_the_snapshot(self, tmp_path, monkeypatch):
        folder = pipeline(tmp_path)
        monkeypatch.chdir(folder)
        result = CliRunner().invoke(main, ["snapshot"])
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert lines.index("Snapshot made. A pipeline that depends on this one gets it with `chartbook update`.") < lines.index(_made_line())
        assert "`chartbook catalog build` renders its site, and `chartbook catalog open` opens it." in lines
        assert config.get_global_catalog_path().is_file()


class TestAtATerminal:
    @pytest.fixture(autouse=True)
    def _a_person(self, monkeypatch):
        monkeypatch.setattr(cli, "_can_ask", lambda: True)

    def test_enter_says_yes(self, stored):
        result = CliRunner().invoke(main, ["ls"], input="\n")
        assert result.exit_code == 0, result.output
        assert "No catalog yet." in result.output
        assert f"Create one over your store at {config.get_store_url()}? [Y/n]: " in result.output
        assert f"Made {config.get_global_catalog_path()}." in result.output
        assert config.get_global_catalog_path().is_file()
        assert "[pipeline] acme/upstream" in result.output

    def test_no_stops_a_command_that_needs_one(self, stored):
        result = CliRunner().invoke(main, ["ls"], input="n\n")
        assert result.exit_code == 1
        assert not config.get_global_catalog_path().exists()
        assert "Run `chartbook catalog init` to make one, or `chartbook config` to point at one you have." in result.output

    def test_no_after_a_snapshot_is_not_an_error(self, tmp_path, monkeypatch):
        folder = pipeline(tmp_path)
        monkeypatch.chdir(folder)
        result = CliRunner().invoke(main, ["snapshot"], input="n\n")
        assert result.exit_code == 0, result.output
        assert "No catalog yet, to show it in." in result.output
        assert not config.get_global_catalog_path().exists()
        # Nor is the end of input, or Ctrl-C there
        result = CliRunner().invoke(main, ["snapshot"], input="")
        assert result.exit_code == 0, result.output
        assert not config.get_global_catalog_path().exists()


class TestLeftAlone:
    def test_catalog_init_asks_nothing(self, tmp_path):
        result = CliRunner().invoke(main, ["catalog", "init"])
        assert result.exit_code == 0, result.output
        made = config.get_global_catalog_path()
        assert result.output.splitlines() == [
            _made_line(),
            "`chartbook catalog build` renders its site, and `chartbook catalog open` opens it.",
        ]
        assert tomli.loads(made.read_text(encoding="utf-8"))["project"]["name"] == "My Catalog"
        again = CliRunner().invoke(main, ["catalog", "init"])
        assert again.exit_code == 0 and "already exists" in again.output
        made.unlink()
        titled = CliRunner().invoke(main, ["catalog", "init", "--title", "Team"])
        assert titled.exit_code == 0, titled.output
        assert tomli.loads(made.read_text(encoding="utf-8"))["project"]["name"] == "Team"

    def test_a_catalog_the_settings_name_is_used(self, tmp_path, monkeypatch):
        folder = pipeline(tmp_path)
        store = tmp_path / "elsewhere"
        snapshot.make(folder, FolderStore(store))
        named = configure(tmp_path, monkeypatch, {"mine": {"url": str(store)}})
        result = CliRunner().invoke(main, ["ls"])
        assert result.exit_code == 0, result.output
        assert "Made " not in result.output
        assert "[pipeline] acme/upstream" in result.output
        assert named.is_file()

    def test_an_old_catalog_is_not_written_over(self, stored):
        old = config.get_global_config_dir() / "chartbook.toml"
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_text('[project]\nname = "Old"\n', encoding="utf-8")
        result = CliRunner().invoke(main, ["ls"])
        assert result.exit_code != 0
        assert "chartbook catalog migrate" in result.output
        assert not config.get_global_catalog_path().exists()

    def test_the_library_makes_it_once_and_says_so(self, stored, capsys):
        from chartbook import data

        frame = data.load(pipeline="acme/upstream", dataframe="dataframe_0")
        assert frame is not None
        assert config.get_global_catalog_path().is_file()
        assert capsys.readouterr().err.strip() == _made_line()


class TestWhatTheReviewFound:
    def test_catalog_init_refuses_beside_an_old_catalog(self, tmp_path):
        old = config.get_global_config_dir() / "chartbook.toml"
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_text('[project]\ntype = "catalog"\nname = "Old"\n', encoding="utf-8")
        result = CliRunner().invoke(main, ["catalog", "init"])
        assert result.exit_code != 0
        assert "chartbook catalog migrate" in result.output
        assert not config.get_global_catalog_path().exists()

    def test_a_snapshot_beside_an_old_catalog_is_still_made(self, tmp_path, monkeypatch):
        """CHARTBOOK_STORE names the store, so the snapshot never reads the catalog; the old one is a note, not a failure."""
        folder = pipeline(tmp_path)
        old = config.get_global_config_dir() / "chartbook.toml"
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_text('[project]\ntype = "catalog"\nname = "Old"\n', encoding="utf-8")
        monkeypatch.chdir(folder)
        result = CliRunner().invoke(main, ["snapshot"])
        assert result.exit_code == 0, result.output
        assert "Snapshot made." in result.output
        assert "Note: no catalog to show it in:" in result.output and "chartbook catalog migrate" in result.output
        assert not config.get_global_catalog_path().exists()

    def test_an_error_hint_makes_no_catalog(self, tmp_path):
        """A read of an undeclared pipeline asks the catalog where it is, to say so: the catalog that is there, never one made for it."""
        from chartbook import data
        from chartbook.errors import DependencyNotDeclaredError

        folder = pipeline(tmp_path)
        with pytest.raises(DependencyNotDeclaredError):
            data.load("acme/other:thing", project_dir=folder)
        assert not config.get_global_catalog_path().exists()

    def test_store_add_makes_it_first_so_the_machines_store_is_listed_first(self, stored, tmp_path):
        from chartbook.store import FolderStore

        other = FolderStore(tmp_path / "other")
        other._check_layout(create=True)
        result = CliRunner().invoke(main, ["store", "add", "team", str(other.root)])
        assert result.exit_code == 0, result.output
        assert list(_stores_of(config.get_global_catalog_path())) == ["default", "team"]

    def test_ls_stores_makes_it(self, stored):
        result = CliRunner().invoke(main, ["ls", "stores"])
        assert result.exit_code == 0, result.output
        assert _made_line() in result.output
        assert f"default: {config.get_store_url()} (writable)" in result.output

    def test_two_at_once_make_one(self, stored):
        made = config.get_global_catalog_path()
        first = config.create_global_catalog(title="First")
        with pytest.raises(FileExistsError):
            config.create_global_catalog(title="Second")
        assert first == made and tomli.loads(made.read_text(encoding="utf-8"))["project"]["name"] == "First"
        assert config.make_default_catalog() == (made, False)
