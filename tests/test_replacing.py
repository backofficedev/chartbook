"""A file or folder put in place while something else holds it for a moment, as a scanner or Google Drive does on Windows."""

import os

import pytest

from chartbook import replacing


def _refused(times, real):
    """*real*, refused with "Access is denied" the first *times* it is asked, as Windows refuses a file a scanner holds."""
    asked = []

    def move(source, target):
        asked.append((source, target))
        if len(asked) <= times:
            raise PermissionError(13, "Access is denied", str(source))
        real(source, target)

    return move, asked


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(replacing, "_WAIT_SECONDS", 0)


def test_a_note_held_a_moment_on_windows_is_replaced_once_it_is_let_go(tmp_path, monkeypatch, quick):
    """The store's note of a lockfile was refused while a scanner read the one before, and the pin failed."""
    note, temporary = tmp_path / "note.json", tmp_path / "note.json.tmp"
    note.write_text("before", encoding="utf-8")
    temporary.write_text("after", encoding="utf-8")
    move, asked = _refused(3, os.replace)
    monkeypatch.setattr(replacing.os, "replace", move)
    monkeypatch.setattr(replacing.sys, "platform", "win32")
    replacing.replace_when_let(temporary, note)
    assert note.read_text(encoding="utf-8") == "after"
    assert len(asked) == 4


def test_a_file_held_for_good_is_said_to_be_after_a_while(tmp_path, monkeypatch, quick):
    move, asked = _refused(1000, os.replace)
    monkeypatch.setattr(replacing.os, "replace", move)
    monkeypatch.setattr(replacing.sys, "platform", "win32")
    with pytest.raises(PermissionError):
        replacing.replace_when_let(tmp_path / "a", tmp_path / "b")
    assert len(asked) == replacing._TRIES


def test_elsewhere_a_refusal_is_said_at_once(tmp_path, monkeypatch, quick):
    """Only Windows refuses for a moment: on another system a refusal is a file's permissions, and lasts."""
    move, asked = _refused(1, os.replace)
    monkeypatch.setattr(replacing.os, "replace", move)
    monkeypatch.setattr(replacing.sys, "platform", "linux")
    with pytest.raises(PermissionError):
        replacing.replace_when_let(tmp_path / "a", tmp_path / "b")
    assert len(asked) == 1


def test_a_folder_held_a_moment_on_windows_is_renamed_once_it_is_let_go(tmp_path, monkeypatch, quick):
    staging, final = tmp_path / ".staging", tmp_path / "final"
    staging.mkdir()
    (staging / "data.parquet").write_bytes(b"numbers")
    move, asked = _refused(2, os.rename)
    monkeypatch.setattr(replacing.os, "rename", move)
    monkeypatch.setattr(replacing.sys, "platform", "win32")
    replacing.rename_when_let(staging, final)
    assert (final / "data.parquet").read_bytes() == b"numbers"
    assert len(asked) == 3


def test_a_folder_another_process_put_there_meanwhile_is_not_waited_on(tmp_path, monkeypatch, quick):
    """Two processes storing the same content: one rename wins, and the other takes what it put there."""
    staging, final = tmp_path / ".staging", tmp_path / "final"
    staging.mkdir()
    final.mkdir()
    move, asked = _refused(1000, os.rename)
    monkeypatch.setattr(replacing.os, "rename", move)
    monkeypatch.setattr(replacing.sys, "platform", "win32")
    with pytest.raises(PermissionError):
        replacing.rename_when_let(staging, final)
    assert len(asked) == 1
