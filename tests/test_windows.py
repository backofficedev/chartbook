"""What Windows asks of ChartBook, tested on any system by saying ``os.name`` is ``nt``."""

import os

import pytest

from chartbook import config, run, store
from chartbook.gitcache import repository_slug


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

    CONNECTED = {"Q:": "\\\\localhost\\c$", "H:": "\\\\files.example.edu\\home\\ab123", "X:": "\\\\files.example.edu\\home"}

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
        ("\\\\other\\share\\work", None),
        ("\\\\localhost\\d$\\work", None),
        ("\\\\localhost", None),
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
        assert run._execute(script, "\\\\localhost\\c$\\cbtest\\report", dict(os.environ)) == 0
        assert [options["cwd"] for options in ran] == ["Q:\\cbtest\\report"]

    @pytest.mark.parametrize("folder, stood_in", [
        ("C:\\cbtest\\report", "C:\\cbtest\\report"),
        ("\\\\?\\C:\\cbtest\\report", "C:\\cbtest\\report"),  # the long spelling of a folder on a drive
    ])
    def test_a_folder_on_a_drive_is_run_in_as_it_is(self, monkeypatch, folder, stood_in):
        ran = []
        monkeypatch.setattr(run, "_connected_drives", lambda: pytest.fail("asked of a folder that is no share"))
        monkeypatch.setattr(run.os, "name", "nt")
        monkeypatch.setattr(run.subprocess, "run", lambda *arguments, **options: ran.append(options) or type("Done", (), {"returncode": 0})())
        run._execute("python build.py", folder, dict(os.environ))
        assert [options["cwd"] for options in ran] == [stood_in]

    def test_a_share_with_no_letter_is_said_and_nothing_runs(self, monkeypatch):
        ran = []
        monkeypatch.setattr(run, "_connected_drives", lambda: {})
        monkeypatch.setattr(run.os, "name", "nt")
        monkeypatch.setattr(run.subprocess, "run", lambda *arguments, **options: ran.append(options))
        with pytest.raises(run.RunError) as refused:
            run._execute("del /q _data\\*", "\\\\files.example.edu\\home\\ab123\\work\\report", dict(os.environ))
        assert str(refused.value) == (
            "\\\\files.example.edu\\home\\ab123\\work\\report is a network folder with no drive letter, and cmd.exe, which "
            "runs a script on Windows, takes no such folder as its own: it would have run the script in C:\\Windows. Connect "
            "the share to a drive letter (`net use Q: \\\\files.example.edu\\home`, with a letter that is free), and run this "
            "again. The script was not run."
        )
        assert ran == []

    def test_no_letter_is_looked_for_on_another_system(self):
        assert run._connected_drives() == {} or os.name == "nt"


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
