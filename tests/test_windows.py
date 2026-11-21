"""What Windows asks of ChartBook, tested on any system by saying ``os.name`` is ``nt``."""

import os

import pytest

from chartbook import config, run, store
from chartbook.gitcache import repository_slug
from tests.test_run import work  # noqa: F401 - a fixture: a folder that is a git repository


class TestALinksTarget:
    def test_the_long_path_prefix_is_not_said(self, monkeypatch):
        monkeypatch.setattr(store.os, "readlink", lambda path: "\\\\?\\C:\\data\\rates.parquet")
        monkeypatch.setattr(store.os, "name", "nt")
        assert store.link_target("x") == "C:\\data\\rates.parquet"

    def test_a_share_is_said_as_a_share(self, monkeypatch):
        monkeypatch.setattr(store.os, "readlink", lambda path: "\\\\?\\UNC\\server\\share\\rates.parquet")
        monkeypatch.setattr(store.os, "name", "nt")
        assert store.link_target("x") == "\\\\server\\share\\rates.parquet"


class TestAFileStoreUrl:
    @pytest.mark.parametrize("url, folder", [
        ("file:///C:/store", "C:/store"),
        ("file://C:/store", "C:/store"),
        ("file://C:\\store", "C:\\store"),
        ("file:///C:", "C:\\"),
        ("file://C:", "C:\\"),
    ])
    def test_a_drive_is_a_folder(self, monkeypatch, url, folder):
        monkeypatch.setattr(config.os, "name", "nt")
        assert config._folder_text(url) == folder

    @pytest.mark.parametrize("url", ["file://server/share", "file://u:pw0rd@host/srv/store"])
    def test_a_host_is_refused_and_no_password_is_said(self, monkeypatch, url):
        monkeypatch.setattr(config.os, "name", "nt")
        with pytest.raises(ValueError, match="names a host") as refused:
            config._folder_text(url)
        assert "pw0rd" not in str(refused.value)


class TestALocalRepositorysClone:
    def test_one_folder_however_its_path_is_written(self):
        forms = ["C:\\repos\\x", "C:/repos/x", "c:\\repos\\x", "file:///C:/repos/x", "file://C:/repos/x"]
        assert len({repository_slug(form) for form in forms}) == 1

    def test_on_windows_a_paths_case_is_no_other_folder(self, monkeypatch):
        from chartbook import gitcache

        # Not os.name itself: a Path made while it says nt is a WindowsPath, which POSIX cannot make
        monkeypatch.setattr(gitcache, "_paths_ignore_case", lambda: True)
        assert repository_slug("C:\\Repos\\X") == repository_slug("c:\\repos\\x")

    def test_its_path_is_short(self):
        deep = "C:/Users/someone/AppData/Local/Temp/" + "/".join(["folder"] * 30) + "/rates"
        assert len(repository_slug(deep).as_posix()) < 40


class TestABatchFile:
    def test_a_character_cmd_cannot_read_is_said_and_nothing_runs(self, monkeypatch, tmp_path):
        ran = []
        monkeypatch.setattr(run, "_batch_encoding", lambda: "cp437")
        monkeypatch.setattr(run.os, "name", "nt")
        monkeypatch.setattr(run.subprocess, "run", lambda *arguments, **options: ran.append(arguments))
        with pytest.raises(run.RunError, match="cannot read in this console's code page"):
            run._execute("python src/a.py\npython src/日本.py\n", tmp_path, dict(os.environ))
        assert ran == []


class TestAScriptInAShare:
    """Found on Windows, 2026-11-20, and as old as `chartbook run`: cmd.exe takes no share as its current folder, and ran the build in C:\\Windows.

    A build of one line of shell ran there, and the run said "Ran build in
    1 pipeline(s)." A drive letter was no cure: a folder is followed to
    where it really is, which for a home folder on a network is the share.
    """

    CONNECTED = [
        ("Q:", "\\\\localhost\\c$"), ("H:", "\\\\files.example.edu\\home\\ab123"), ("X:", "\\\\files.example.edu\\home\\"),
        # A letter under two names of its share: as it was connected, and as its folder is followed to
        ("N:", "\\\\campus.example.edu\\dfs\\home"), ("N:", "\\\\fs07.example.edu\\home$"),
        ("B:", "\\\\server"), ("B:", ""),  # no share: never a letter for anything
    ]

    @pytest.mark.parametrize("folder, lettered", [
        ("\\\\localhost\\c$\\cbtest\\n4\\plain\\report", "Q:\\cbtest\\n4\\plain\\report"),
        ("\\\\LOCALHOST\\C$\\cbtest\\My Work", "Q:\\cbtest\\My Work"),  # a share's name is one whatever its letter case
        ("//localhost/c$/cbtest/report", "Q:\\cbtest\\report"),
        ("\\\\?\\UNC\\localhost\\c$\\cbtest\\report", "Q:\\cbtest\\report"),  # the long spelling of it
        ("\\\\localhost\\c$", "Q:\\"),  # the share's own folder: not `Q:`, which is wherever one last stood on it
        ("\\\\localhost\\c$\\", "Q:\\"),
        # Two letters lead there: the one nearest the folder
        ("\\\\files.example.edu\\home\\ab123\\work\\report", "H:\\work\\report"),
        ("\\\\files.example.edu\\home\\cd456\\work", "X:\\cd456\\work"),
        ("\\\\files.example.edu\\home\\ab1234\\work", "X:\\ab1234\\work"),  # `ab1234` is no folder of `ab123`
        # Found by review: a share reached through a name that stands for several servers is named either way
        ("\\\\fs07.example.edu\\home$\\ab123\\work", "N:\\ab123\\work"),
        ("\\\\campus.example.edu\\dfs\\home\\ab123\\work", "N:\\ab123\\work"),
        ("\\\\other\\share\\work", None),
        ("\\\\localhost\\d$\\work", None),
        ("\\\\files.example.edu.evil.org\\home\\ab123", None),
        ("\\\\files.example.edu\\homes\\ab123", None),
        ("\\\\localhost", None),
        ("\\\\server\\share\\x", None),  # a letter that names a server alone leads nowhere
    ])
    def test_a_share_is_named_by_a_letter_connected_to_it(self, folder, lettered):
        assert run._by_its_drive_letter(folder, self.CONNECTED) == lettered

    @pytest.mark.parametrize("script", ["python build.py", "python a.py\npython b.py\n"])
    def test_the_script_is_run_from_the_letter(self, monkeypatch, tmp_path, script):
        """Both ways a script is handed to cmd.exe: a line as it is, and several as a file."""
        ran = []
        monkeypatch.setattr(run, "_batch_encoding", lambda: "cp437")
        monkeypatch.setattr(run, "_connected_drives", lambda: self.CONNECTED)
        monkeypatch.setattr(run.os, "name", "nt")
        monkeypatch.setattr(run.subprocess, "run", lambda *arguments, **options: ran.append(options) or type("Done", (), {"returncode": 0})())
        assert run._execute(script, "\\\\localhost\\c$\\cbtest\\report", {"PATH": "x"}) == 0
        assert [(options["cwd"], options["env"]) for options in ran] == [("Q:\\cbtest\\report", {"PATH": "x"})]

    @pytest.mark.parametrize("folder, stood_in", [
        ("C:\\cbtest\\report", "C:\\cbtest\\report"),
        ("\\\\?\\C:\\cbtest\\report", "C:\\cbtest\\report"),  # the long spelling of a folder on a drive
        # Found by review: these are no shares, and were said to be. They are left as they were given
        ("\\\\.\\C:\\cbtest", "C:\\cbtest"),
        ("\\\\?\\Volume{1b3f}\\x", "\\\\?\\Volume{1b3f}\\x"),
        ("\\\\?\\C:", "\\\\?\\C:"),
        ("\\\\.\\pipe\\x", "\\\\.\\pipe\\x"),
    ])
    def test_a_folder_that_is_no_share_is_run_in_as_it_is(self, monkeypatch, folder, stood_in):
        ran = []
        monkeypatch.setattr(run, "_connected_drives", lambda: pytest.fail("asked of a folder that is no share"))
        monkeypatch.setattr(run.os, "name", "nt")
        monkeypatch.setattr(run.subprocess, "run", lambda *arguments, **options: ran.append(options) or type("Done", (), {"returncode": 0})())
        run._execute("python build.py", folder, dict(os.environ))
        assert [options["cwd"] for options in ran] == [stood_in]

    REFUSED = (
        "{folder} is a network folder with no drive letter, and cmd.exe, which runs a script on Windows, takes no such "
        "folder as its own: it would have run the script in C:\\Windows. Connect the share to a drive letter "
        "(`net use Q: {share}`, with a letter that is free), and run this again."
    )

    def test_a_share_with_no_letter_is_said_and_nothing_runs(self, monkeypatch):
        ran = []
        monkeypatch.setattr(run, "_connected_drives", lambda: [])
        monkeypatch.setattr(run.os, "name", "nt")
        monkeypatch.setattr(run.subprocess, "run", lambda *arguments, **options: ran.append(options))
        folder = "\\\\files.example.edu\\home\\ab123\\work\\report"
        with pytest.raises(run.RunError) as refused:
            run._execute("del /q _data\\*", folder, dict(os.environ))
        assert str(refused.value) == self.REFUSED.format(folder=folder, share='"\\\\files.example.edu\\home"') + " The script was not run."
        assert ran == []

    @pytest.mark.parametrize("folder, share", [
        # Found by review: the share was printed bare, which is two words where its name has a space, and in
        # Git Bash loses its backslashes
        ("\\\\server\\my share\\work\\report", '"\\\\server\\my share"'),
        ("\\\\server\\R&D\\x", "ITS-NAME-HOLDS-A-SIGN-A-SHELL-READS"),
    ])
    def test_the_share_to_connect_is_one_word_of_the_command(self, monkeypatch, folder, share):
        monkeypatch.setattr(run, "_connected_drives", lambda: [])
        with pytest.raises(run.RunError) as refused:
            run._as_cmd_takes_it(folder)
        assert str(refused.value) == self.REFUSED.format(folder=folder, share=share)

    def test_it_is_known_before_anything_is_built(self, monkeypatch):
        """Found by review: the refusal came when the step was reached, after whatever it depends on had been built and snapshotted."""
        from types import SimpleNamespace

        monkeypatch.setattr(run, "_connected_drives", lambda: self.CONNECTED)
        nowhere = "\\\\other\\share\\"
        asked = SimpleNamespace(id="acme/report", source="asked", scripts={"build": "x"}, directory=nowhere + "report")
        with pytest.raises(run.RunError) as refused:
            run._no_script_in_a_share_without_a_letter([asked], "build", windows=True)
        assert str(refused.value) == (
            "acme/report: " + self.REFUSED.format(folder=nowhere + "report", share='"\\\\other\\share"') + " Nothing was built."
        )
        # Found by the same review, a pass later: only of what is sure to be run. A pipeline that was asked for
        # and has the script, in a share that has its letter; one that has no such script; what it depends on,
        # which may be built already (an upstream with its snapshot, a git dependency); and one with no folder
        steps = [
            SimpleNamespace(id="acme/here", source="asked", scripts={"build": "x"}, directory="\\\\localhost\\c$\\cbtest\\here"),
            SimpleNamespace(id="acme/other", source="asked", scripts={"lab": "x"}, directory=nowhere + "other"),
            SimpleNamespace(id="acme/up", source="upstream", scripts={"build": "x"}, directory=nowhere + "up"),
            SimpleNamespace(id="acme/data", source="git", scripts={}, directory=nowhere + "cache\\checkouts\\data"),
            SimpleNamespace(id="acme/elsewhere", source="asked", scripts={"build": "x"}, directory=None),
        ]
        run._no_script_in_a_share_without_a_letter(steps, "build", windows=True)
        # On another system a folder is run in as it is, whatever its name
        monkeypatch.setattr(run, "_connected_drives", lambda: pytest.fail("asked on a system that is not Windows"))
        run._no_script_in_a_share_without_a_letter([asked], "build", windows=False)

    @pytest.mark.parametrize("given, handed", [
        # The folder a git dependency's build is told to look no further up than: by the letter's name too
        ("\\\\localhost\\c$\\cache\\checkouts", "\\\\localhost\\c$\\cache\\checkouts;Q:\\cache\\checkouts"),
        ("//localhost/c$/cache/checkouts/", "//localhost/c$/cache/checkouts/;Q:\\cache\\checkouts"),
        # Found by review: one the person set for themselves is theirs. With the pipeline's parent added to it,
        # git in the build no longer found the repository the pipeline is a folder of
        ("C:\\Users\\me", "C:\\Users\\me"),
        ("\\\\localhost\\c$\\cache", "\\\\localhost\\c$\\cache"),
    ])
    def test_git_is_told_the_folder_to_stop_at_by_the_letter_too(self, monkeypatch, given, handed):
        """Found by review: a git dependency's build is told where git is to look no further up, by the share's name; git in the script stands on the letter."""
        ran = []
        monkeypatch.setattr(run, "_connected_drives", lambda: self.CONNECTED)
        monkeypatch.setattr(run.os, "name", "nt")
        monkeypatch.setattr(run.os, "pathsep", ";")
        monkeypatch.setattr(run.subprocess, "run", lambda *arguments, **options: ran.append(options) or type("Done", (), {"returncode": 0})())
        environment = {"GIT_CEILING_DIRECTORIES": given}
        run._execute("python build.py", "\\\\localhost\\c$\\cache\\checkouts\\rates", environment)
        assert ran[0]["env"] == {"GIT_CEILING_DIRECTORIES": handed}
        assert environment == {"GIT_CEILING_DIRECTORIES": given}  # the caller's own is as it was

    def test_a_share_typed_with_forward_slashes_is_one_too(self, monkeypatch):
        monkeypatch.setattr(run, "_connected_drives", lambda: self.CONNECTED)
        assert run._as_cmd_takes_it("//localhost/c$/cbtest/report") == "Q:\\cbtest\\report"

    @pytest.mark.skipif(os.name == "nt", reason="the scripts here are POSIX shell")
    def test_a_run_asks_it_of_the_steps_it_planned_before_any_script(self, work, monkeypatch):
        from tests.test_run import LOG, _commit, _order, _with_data

        pipeline = _with_data(work / "p", {"build": LOG})
        _commit(work)
        asked = []

        def refuse(steps, script, windows=None):
            asked.append(([step.id for step in steps], script))
            raise run.RunError("p: … is a network folder with no drive letter … Nothing was built.")

        monkeypatch.setattr(run, "_no_script_in_a_share_without_a_letter", refuse)
        with pytest.raises(run.RunError, match="is a network folder with no drive letter"):
            run.run(pipeline, echo=lambda line: None)
        assert asked == [(["p"], "build")] and _order(work) == []

    def test_no_letter_is_looked_for_on_another_system(self):
        assert run._connected_drives() == [] or os.name == "nt"


class TestRemovingAStagingFolder:
    def test_nothing_above_it_is_touched(self, tmp_path):
        from chartbook.gitcache import _remove_staging

        above = tmp_path / "slug"
        above.mkdir()
        os.chmod(above, 0o755)
        before = os.stat(above).st_mode  # on Windows, a folder's mode is 0o777 whatever chmod says
        _remove_staging(above / "gone-already.tmp")
        assert os.stat(above).st_mode == before

    @pytest.mark.skipif(os.name == "nt", reason="a folder no one may list is a POSIX one")
    def test_a_folder_that_cannot_be_listed_raises_nothing(self, tmp_path):
        from chartbook.gitcache import _remove_staging

        staging = tmp_path / "staging.tmp"
        (staging / "locked").mkdir(parents=True)
        os.chmod(staging / "locked", 0)
        try:
            _remove_staging(staging)
        finally:
            if (staging / "locked").exists():
                os.chmod(staging / "locked", 0o700)


class TestAFileOfTheStoreInAMessage:
    """A message names a file of a folder store as the system it is on writes a path: with one kind of separator.

    Found on Windows, where a message read ``C:\\…\\store/snapshots/acme+rates/…``,
    which is no path to paste. Windows' own join stands in for the system's
    here, by the one name the store joins with.
    """

    @pytest.fixture
    def there(self, tmp_path, monkeypatch):
        import ntpath

        monkeypatch.setattr(store, "_join", ntpath.join)
        return store.FolderStore(tmp_path / "store")

    def test_a_path_is_joined_as_the_system_joins_one(self, there):
        record = there.root / "snapshots" / "acme+rates" / "2026-11-16T091500Z_aaaaaaaaaaaa" / "_chartbook" / "snapshot.json"
        assert there._shown(record) == f"{there}\\snapshots\\acme+rates\\2026-11-16T091500Z_aaaaaaaaaaaa\\_chartbook\\snapshot.json"
        assert there._shown(there.root) == str(there)

    def test_so_is_a_name_under_the_store(self, there):
        """What a removal that failed is named by: its name under the store, which is written with ``/`` wherever it is kept."""
        assert there.shown("snapshots/acme+rates/2026-11-16T091500Z_aaaaaaaaaaaa/_data/rates.parquet") == (
            f"{there}\\snapshots\\acme+rates\\2026-11-16T091500Z_aaaaaaaaaaaa\\_data\\rates.parquet"
        )

    def test_a_note_that_cannot_be_read_is_named_so(self, there):
        notes = there.roots_path()
        notes.mkdir(parents=True)
        (notes / "half-synced.json").write_text("{", encoding="utf-8", newline="\n")
        with pytest.raises(store.StoreError) as refused:
            there.roots()
        folder = "\\".join(notes.relative_to(there.root).parts)
        assert str(refused.value).startswith(f"Cannot read {there}\\{folder}\\half-synced.json: ")

    def test_a_bucket_keeps_its_address_and_the_name(self):
        """A store that is not a folder has no system's separator: its address, a ``/`` and the name."""

        class Bucket:
            def __str__(self):
                return "s3://bucket/store"

        assert store.Store.shown(Bucket(), "snapshots/acme+rates/a.parquet") == "s3://bucket/store/snapshots/acme+rates/a.parquet"
