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


class TestRemovingAStagingFolder:
    def test_nothing_above_it_is_touched(self, tmp_path):
        from chartbook.gitcache import _remove_staging

        above = tmp_path / "slug"
        above.mkdir()
        os.chmod(above, 0o755)
        _remove_staging(above / "gone-already.tmp")
        assert (os.stat(above).st_mode & 0o777) == 0o755

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
