"""Where a pipeline's folder is in git: ``snapshot.code_of``.

A folder is placed in its repository by the name the disk has for each
part of its path. A disk that does not tell letter cases apart, or the two
of Unicode's forms, opens a folder by a name other than its own, and
``Path.resolve`` keeps the name that was typed (on macOS), while git gives
the disk's for the repository's top. Found on a Mac, on main, each with
pathlib's own words or a record of the spelling that was typed:

- a ``[dependencies]`` entry ``path = "../UP"`` of a folder named ``up``
  stopped ``chartbook run`` at the pin with ``'…/UP' is not in the subpath
  of '…/up'``;
- ``chartbook run --upstream --project-dir …/mono/PIPES/report`` recorded
  the upstream's snapshot under ``PIPES/a``, where the disk has ``pipes/a``;
- with ``MONO/pipes/report`` it stopped with ``is not in the subpath``.

Git's own word for the place (``rev-parse --show-prefix``) would not do
either: it writes a name in Unicode's composed form whichever the disk
has. And a repository whose ``core.worktree`` names another folder
answers with a top the folder is not under, which is said in words.
"""

import os
import unicodedata
from pathlib import Path

import pytest

from chartbook import lock, snapshot
from chartbook.snapshot import SnapshotError
from tests.test_run_builds_and_snapshot_is_typed import (  # noqa: F401 - work and store are fixtures
    DEMO,
    _committed,
    _folder,
    _run,
    _snapshot_of,
    _snapshots,
    _write,
    posix,
    store,
    work,
)
from tests.test_lock_by_kind import _git


def _other_case(folder: Path, *parts: str) -> Path:
    """A folder under *folder* by these parts, which spell it in another letter case than the disk's; skipped where the disk tells letter cases apart."""
    other = folder.joinpath(*parts)
    if not other.is_dir():
        pytest.skip("this disk tells letter cases apart")
    return other


@pytest.fixture
def mono(work):
    """A repository ``mono`` with a pipeline at ``pipes/a``; the pipeline's folder."""
    a = _folder(work / "mono" / "pipes" / "a")
    _committed(work / "mono")
    return a


class TestAnotherLetterCase:
    def test_a_folder_inside_the_repository_is_placed_by_the_disks_name(self, mono, work):
        code = snapshot.code_of(_other_case(work, "mono", "PIPES", "A"))
        assert code.subdirectory == "pipes/a" and code.top == work / "mono"
        assert code == snapshot.code_of(mono)

    def test_so_is_one_whose_repository_is_spelled_otherwise(self, mono, work):
        """Pathlib's own words came back: the folder, as typed, is not under the top, as git gives it."""
        code = snapshot.code_of(_other_case(work, "MONO", "pipes", "a"))
        assert code.subdirectory == "pipes/a" and str(code.top) == str(work / "mono")

    def test_and_the_repositorys_own_folder(self, mono, work):
        code = snapshot.code_of(_other_case(work, "MONO"))
        assert code.subdirectory == "" and str(code.top) == str(work / "mono")

    def test_only_a_name_its_folder_does_not_list_is_looked_for(self, mono, work, monkeypatch):
        """Each parent is listed, and no entry of it is looked at where the name is listed as it is."""
        other = _other_case(work, "mono", "PIPES", "a")
        asked = []
        same = os.path.samefile

        def samefile(one, another):
            asked.append(Path(another))
            return same(one, another)

        monkeypatch.setattr(os.path, "samefile", samefile)
        assert snapshot.code_of(mono).subdirectory == "pipes/a" and asked == []
        assert snapshot.code_of(other).subdirectory == "pipes/a"
        # The one part that is spelled otherwise, where resolving the path kept the spelling that was typed
        # (macOS). Windows hands back the disk's names as it resolves, and then nothing is looked for at all
        kept_as_typed = str(other.resolve()) == str(other)
        assert {str(path) for path in asked} == ({str(work / "mono" / "PIPES")} if kept_as_typed else set())

    def test_where_the_disk_has_both_each_is_its_own(self, work):
        """A disk that tells letter cases apart may hold ``rates`` and ``RATES``: the name that is listed is the one."""
        for name in ("rates", "RATES"):
            (work / "both" / name).mkdir(parents=True, exist_ok=True)
        if len(os.listdir(work / "both")) != 2:
            pytest.skip("this disk does not tell letter cases apart")
        _committed(work / "both")
        assert [snapshot.code_of(work / "both" / name).subdirectory for name in ("rates", "RATES")] == ["rates", "RATES"]


@posix
class TestAsItWasFound:
    """The three, through the commands."""

    def test_a_path_dependency_spelled_in_another_letter_case_is_pinned(self, work, store, monkeypatch):
        up = _committed(_folder(work / "up", {**DEMO, "project": {"id": "acme/up"}}))
        _other_case(work, "UP")
        _snapshot_of(up, store)
        demo = _folder(work / "demo", {**DEMO, "dependencies": {"acme/up": {"path": "../UP"}}})
        monkeypatch.chdir(_committed(demo))
        result = _run()
        assert result.exit_code == 0 and "is not in the subpath" not in result.output, result.output
        (taken,) = _snapshots(store)
        (entry,) = lock.read_lock(demo).dependencies
        assert entry["snapshot"] == taken.made_at and taken.subdirectory == ""

    @pytest.mark.parametrize("spelled", [("mono", "PIPES", "report"), ("MONO", "pipes", "report")])
    def test_an_upstream_built_for_a_folder_spelled_otherwise_is_recorded_under_the_disks_name(self, mono, work, store, monkeypatch, spelled):
        """`run --upstream --project-dir` hands its own spelling on to the upstream it builds, by the path between the two."""
        _write(mono, {**DEMO, "project": {"id": "acme/a"}})
        report = _folder(work / "mono" / "pipes" / "report", {**DEMO, "dependencies": {"acme/a": {"path": "../a"}}})
        _committed(work / "mono")
        other = _other_case(work, *spelled)
        monkeypatch.chdir(work)
        result = _run("--upstream", "--project-dir", str(other))
        assert result.exit_code == 0 and "is not in the subpath" not in result.output, result.output
        (taken,) = _snapshots(store)
        assert taken.pipeline == "acme/a" and taken.subdirectory == "pipes/a"
        (entry,) = lock.read_lock(report).dependencies
        assert entry["snapshot"] == taken.made_at


class TestTheOtherOfUnicodesForms:
    """``é`` is one character (NFC) or an ``e`` and an accent (NFD). The disk has one of them, and opens the folder by either."""

    @pytest.mark.parametrize("on_disk, typed", [("NFC", "NFD"), ("NFD", "NFC")])
    def test_the_folder_is_placed_by_the_form_the_disk_has(self, work, on_disk, typed):
        name = "dépôt"
        directory = _folder(work / "mono" / unicodedata.normalize(on_disk, name) / "pipe")
        _committed(work / "mono")
        other = work / "mono" / unicodedata.normalize(typed, name) / "pipe"
        if not other.is_dir():
            pytest.skip("this disk tells the two forms apart")
        (listed,) = [entry for entry in os.listdir(work / "mono") if not entry.startswith(".")]  # the disk's own word for it
        assert str(other) != str(directory)
        for spelled in (directory, other):
            assert snapshot.code_of(spelled).subdirectory == f"{listed}/pipe"

    def test_git_would_have_given_another_than_the_disk_has(self, work):
        """Why git's own word for the place is not asked: where git composes names (macOS), a folder the disk has in the other form comes back composed."""
        name = unicodedata.normalize("NFD", "dépôt")
        directory = _folder(work / "mono" / name / "pipe")
        _committed(work / "mono")
        (listed,) = [entry for entry in os.listdir(work / "mono") if not entry.startswith(".")]
        said = snapshot._git(directory, "rev-parse", "--show-prefix").strip().rstrip("/")
        if said == f"{listed}/pipe":
            pytest.skip("git gives the disk's form here")
        assert unicodedata.normalize("NFC", said) == unicodedata.normalize("NFC", f"{listed}/pipe")
        assert snapshot.code_of(directory).subdirectory == f"{listed}/pipe"


#: What git says of a repository on a network share (and on a drive letter mapped to one), on Windows: it ends 128
ON_A_SHARE = (
    "fatal: detected dubious ownership in repository at '//server/share/work/rates'\n"
    "'//server/share/work/rates' is owned by:\n"
    "\t(inconvertible) (S-1-5-21-1004336348-1177238915-682003330-1001)\n"
    "but the current user is:\n"
    "\tDESKTOP/someone (S-1-5-21-2127521184-1604012920-1887927527-1001)\n"
    "To add an exception for this directory, call:\n"
    "\n"
    "\tgit config --global --add safe.directory '%(prefix)///server/share/work/rates'"
)
#: And of another user's repository on Linux or macOS
ANOTHER_USERS = (
    "fatal: detected dubious ownership in repository at '/srv/shared/work/rates'\n"
    "To add an exception for this directory, call:\n"
    "\n"
    "\tgit config --global --add safe.directory /srv/shared/work/rates"
)


class TestARepositoryGitDoesNotTrust:
    """Git reads no repository that another user owns until it is told to, and on Windows a network share is such a one.

    Found on Windows: ``… is not in a git repository. A snapshot is
    labelled with the commit it was built from, so only a pipeline that is
    in git has any``, of a pipeline that is in git, with nothing to do
    about it. Git's own refusal stands in for a share here: what
    ``code_of`` runs git with fails with git's words.
    """

    @staticmethod
    def _refusing(monkeypatch, words: str) -> None:
        def refuse(directory, *arguments, **options):
            raise SnapshotError(words)  # as snapshot._git raises what git said when it fails

        monkeypatch.setattr(snapshot, "_git", refuse)

    @pytest.mark.parametrize("words, repository, trusted", [
        (ON_A_SHARE, "//server/share/work/rates", "%(prefix)///server/share/work/rates"),
        (ANOTHER_USERS, "/srv/shared/work/rates", "/srv/shared/work/rates"),
    ])
    def test_it_is_said_with_the_command_that_makes_git_trust_it(self, work, monkeypatch, words, repository, trusted):
        from chartbook.missing import _quoted

        directory = _folder(work / "rates")
        self._refusing(monkeypatch, words)
        with pytest.raises(SnapshotError) as refused:
            snapshot.code_of(directory)
        assert str(refused.value) == (
            f"git does not trust the repository that {directory} is in ({repository}): another user owns it, or it is "
            f"on a network share, and git reads no such repository until it is told to. To have git trust it, run "
            f"`git config --global --add safe.directory {_quoted(trusted, batch=False)}`, and then this again"
        )
        assert "is not in a git repository" not in str(refused.value)
        # The command is also had apart from the sentence, and is the one in it
        assert refused.value.command == f"git config --global --add safe.directory {_quoted(trusted, batch=False)}"
        assert f"run `{refused.value.command}`, and then this again" in str(refused.value)

    @staticmethod
    def _as_on_windows(monkeypatch) -> None:
        """The sentence's command as it is written on Windows, on any system: the word is quoted for its shells."""
        from chartbook import missing

        real = missing._quoted
        monkeypatch.setattr(
            missing, "_quoted",
            lambda text, windows=None, batch=True, backslashes=False: real(text, windows=True, batch=batch, backslashes=backslashes),
        )

    def test_on_windows_a_shares_folder_is_in_the_command(self, work, monkeypatch):
        """Found by the review of what prints this sentence: the word git writes for a share begins
        `%(prefix)/`, and for its `%` the command read `safe.directory ITS-NAME-HOLDS-A-SIGN-A-SHELL-READS`.
        The word is handed to git, a program: typed on Windows 11, 2026-11-20, it is text in double
        quotes in cmd.exe, Windows PowerShell and Git Bash."""
        self._as_on_windows(monkeypatch)
        refusal = snapshot._not_trusted_by_git(work / "rates", ON_A_SHARE)
        said = str(refusal)
        assert said.endswith(
            'To have git trust it, run `git config --global --add safe.directory "%(prefix)///server/share/work/rates"`, '
            "and then this again"
        )
        assert "ITS-NAME" not in said
        # And the command apart from the sentence, for what gives it as a line of its own
        assert refusal.command == 'git config --global --add safe.directory "%(prefix)///server/share/work/rates"'

    @pytest.mark.parametrize("folder", ["//server/share/%CD%/rates", "//server/share/a`b/rates", "//server/share/$(calc)/rates"])
    def test_on_windows_a_folder_no_shell_takes_as_text_gets_no_command_of_ours(self, work, monkeypatch, folder):
        """The sentence never tells a person to run a command with a placeholder in it: git prints its own in that folder."""
        import shlex

        self._as_on_windows(monkeypatch)
        words = (
            f"fatal: detected dubious ownership in repository at '{folder}'\n"
            "To add an exception for this directory, call:\n\n"
            f"\tgit config --global --add safe.directory {shlex.quote('%(prefix)/' + folder)}"
        )
        refusal = snapshot._not_trusted_by_git(work / "rates", words)
        assert refusal.command == ""  # none of ours to give
        assert str(refusal) == (
            f"git does not trust the repository that {work / 'rates'} is in ({folder}): another user owns it, or it is "
            "on a network share, and git reads no such repository until it is told to. To have git trust it, run the "
            "`git config --global --add safe.directory` command that `git status` prints in that folder (in PowerShell or "
            "Git Bash: `cmd.exe` does not read its quotes), and then this again"
        )

    def test_it_is_an_error_of_its_own_class_and_no_other_case_is(self, work, monkeypatch):
        """For what must tell this case from the others without reading the sentence: ``snapshot.RepositoryNotTrusted``, a ``SnapshotError``. Every other case raises a ``SnapshotError`` that is not one."""
        directory = _folder(work / "rates")
        others = [work / "no-such-folder"]  # no folder there
        begun = _folder(work / "begun")
        _git(begun, "init", "--quiet", "-b", "main")
        others.append(begun)  # a repository with no commit yet
        elsewhere = _committed(_folder(work / "repo"))
        (work / "elsewhere").mkdir()
        _git(elsewhere, "config", "core.worktree", str(work / "elsewhere"))
        others.append(elsewhere)  # git gives a top the folder is not under
        for other in others:
            with pytest.raises(SnapshotError) as refused:
                snapshot.code_of(other)
            assert type(refused.value) is SnapshotError, (other, refused.value)
        # A folder in no repository has a class of its own too, for the list of what is not in a store, which has shorter words for it
        with pytest.raises(snapshot.NotInARepository) as refused:
            snapshot.code_of(directory)
        assert isinstance(refused.value, SnapshotError) and str(refused.value).startswith(f"{directory} is not in a git repository. ")
        for words, kind in (
            ("fatal: not a git repository (or any of the parent directories): .git", snapshot.NotInARepository),
            ("fatal: not a git repository: /srv/safe.directory-notes/main/.git/worktrees/tree", snapshot.NotInARepository),
            ("git could not be run: [Errno 2] No such file or directory: 'git'", SnapshotError),
        ):
            self._refusing(monkeypatch, words)
            with pytest.raises(SnapshotError) as refused:
                snapshot.code_of(directory)
            assert type(refused.value) is kind, (words, refused.value)
        for words in (ON_A_SHARE, ANOTHER_USERS):
            self._refusing(monkeypatch, words)
            with pytest.raises(snapshot.RepositoryNotTrusted) as refused:
                snapshot.code_of(directory)
            assert isinstance(refused.value, SnapshotError) and str(refused.value).startswith("git does not trust the repository that ")

    def test_the_folder_in_the_command_is_quoted_for_this_systems_shell(self, work, monkeypatch):
        """A share's folder as git writes it has a ``%`` and brackets; one with a space is one word of the command all the same."""
        from chartbook.missing import _quoted

        self._refusing(monkeypatch, (
            "fatal: detected dubious ownership in repository at '/srv/shared work/rates'\n"
            "To add an exception for this directory, call:\n"
            "\n"
            "\tgit config --global --add safe.directory '/srv/shared work/rates'"
        ))
        with pytest.raises(SnapshotError) as refused:
            snapshot.code_of(_folder(work / "rates"))
        assert f"`git config --global --add safe.directory {_quoted('/srv/shared work/rates')}`" in str(refused.value)
        assert _quoted("/srv/shared work/rates") != "/srv/shared work/rates"

    def test_without_gits_line_for_it_the_repository_git_names_is_the_folder(self, work, monkeypatch):
        self._refusing(monkeypatch, "fatal: detected dubious ownership in repository at '/srv/shared/work/rates'")
        with pytest.raises(SnapshotError, match=r"run `git config --global --add safe\.directory /srv/shared/work/rates`, and then this again$"):
            snapshot.code_of(_folder(work / "rates"))

    def test_a_folder_in_no_repository_is_still_said_to_be_in_none(self, work):
        """Git itself, of a folder outside any repository: the message is as it was."""
        directory = work / "plain"
        directory.mkdir()
        with pytest.raises(SnapshotError) as refused:
            snapshot.code_of(directory)
        assert str(refused.value) == (
            f"{directory} is not in a git repository. A snapshot is labelled with the commit it was built from, so only a "
            f"pipeline that is in git has any"
        )

    def test_any_other_failure_of_git_keeps_that_message_too(self, work, monkeypatch):
        directory = _folder(work / "rates")
        self._refusing(monkeypatch, "fatal: not a git repository (or any of the parent directories): .git")
        with pytest.raises(SnapshotError, match="is not in a git repository"):
            snapshot.code_of(directory)

    @pytest.mark.parametrize("words", [
        # In German: the sentence is translated, and the command is not
        "fatal: zweifelhafter Besitz im Repository unter '/srv/geteilt/rates' erkannt\n"
        "Um eine Ausnahme für dieses Verzeichnis hinzuzufügen, rufen Sie auf:\n\n\tgit config --global --add safe.directory /srv/geteilt/rates",
        # Of git 2.35, before it had the sentence
        "fatal: unsafe repository ('/srv/geteilt/rates' is owned by someone else)\n"
        "To add an exception for this directory, call:\n\n\tgit config --global --add safe.directory /srv/geteilt/rates",
    ])
    def test_gits_line_for_it_alone_says_it_in_any_language_and_of_an_older_git(self, work, monkeypatch, words):
        self._refusing(monkeypatch, words)
        with pytest.raises(SnapshotError) as refused:
            snapshot.code_of(_folder(work / "rates"))
        assert "is in (/srv/geteilt/rates): another user owns it" in str(refused.value)
        assert str(refused.value).endswith("run `git config --global --add safe.directory /srv/geteilt/rates`, and then this again")

    def test_a_repository_whose_path_has_an_apostrophe_is_named_whole(self, work, monkeypatch):
        """Found by review: git writes the repository between apostrophes, and a folder's name may have one (``the team's work``): the message named the path up to it. It is taken from git's command line, where git quotes it for a shell."""
        from chartbook.missing import _quoted

        at = "/srv/the team's work/rates"
        self._refusing(monkeypatch, (
            f"fatal: detected dubious ownership in repository at '{at}'\n"
            "To add an exception for this directory, call:\n"
            "\n"
            "\tgit config --global --add safe.directory '/srv/the team'\\''s work/rates'"
        ))
        with pytest.raises(SnapshotError) as refused:
            snapshot.code_of(_folder(work / "rates"))
        assert f"is in ({at}): another user owns it" in str(refused.value), str(refused.value)
        assert str(refused.value).endswith(f"run `git config --global --add safe.directory {_quoted(at)}`, and then this again")
        # And without the command line, from git's sentence, to the apostrophe that ends it
        self._refusing(monkeypatch, f"fatal: detected dubious ownership in repository at '{at}'")
        with pytest.raises(SnapshotError) as refused:
            snapshot.code_of(work / "rates")
        assert f"is in ({at}): another user owns it" in str(refused.value), str(refused.value)

    def test_a_failure_that_only_has_safe_directory_in_it_is_not_this_one(self, work):
        """Found by review: any failure of git with ``safe.directory`` in its words was taken for git's refusal to trust the repository, and the person was told to run a ``git config`` that changes nothing.

        Here git itself fails, of a worktree whose repository has been
        moved away, under a folder of that name."""
        from chartbook.replacing import rename_when_let

        top = work / "safe.directory-notes"
        directory = _committed(_folder(top / "main"))
        _git(directory, "worktree", "add", "--quiet", str(top / "tree"), "-b", "other")
        tree = top / "tree"
        assert snapshot.code_of(tree).subdirectory == ""
        rename_when_let(directory, top / "gone")
        with pytest.raises(SnapshotError) as refused:
            snapshot.code_of(tree)
        assert str(refused.value) == (
            f"{tree} is not in a git repository. A snapshot is labelled with the commit it was built from, so only a "
            f"pipeline that is in git has any"
        )

    def test_git_that_cannot_be_run_is_said_as_that(self, work, monkeypatch):
        """Found by review: with git not installed, or not on the PATH (a new Windows machine), the folder was said to be in no git repository. Nothing is known of the folder then, and what is known is said."""
        import subprocess

        directory = _committed(_folder(work / "rates"))

        def not_there(*arguments, **options):
            raise FileNotFoundError(2, "No such file or directory", "git")

        monkeypatch.setattr(subprocess, "run", not_there)
        with pytest.raises(SnapshotError) as refused:
            snapshot.code_of(directory)
        assert str(refused.value) == "git could not be run: [Errno 2] No such file or directory: 'git'"


class TestARepositoryWhoseFilesAreElsewhere:
    def test_a_folder_git_does_not_place_under_its_top_is_said_in_words(self, work):
        """``core.worktree`` set to another folder: git answers with that folder as the top, and the pipeline's is not under it."""
        directory = _committed(_folder(work / "repo"))
        (work / "elsewhere").mkdir()
        _git(directory, "config", "core.worktree", str(work / "elsewhere"))
        with pytest.raises(SnapshotError) as refused:
            snapshot.code_of(directory)
        assert str(refused.value) == (
            f"{directory} is not under {work / 'elsewhere'}, which is where git says the files of its repository are: "
            f"the repository's core.worktree names another folder than its own. A snapshot records "
            f"where a pipeline is in its repository, so it is made of a folder under that one"
        )

    @pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="a folder's mode stops no listing here")
    def test_that_is_said_only_where_the_repository_sets_it(self, work):
        """Found by review: a folder typed in another letter case, under a parent that may be passed through and not listed.

        The parent's listing is what gives the disk's name, so the name
        stays as typed; git gives the disk's; and the folder is not under
        the top. The message said "the repository's core.worktree names
        another folder than its own, most likely", of a repository that
        sets none. It says what is known: the two folders, and that the
        one is not under the other."""
        import stat

        parent = work / "shared"
        directory = _committed(_folder(parent / "Repo"))
        typed = _other_case(parent, "repo")
        os.chmod(parent, stat.S_IWUSR | stat.S_IXUSR)  # passed through, not listed
        try:
            with pytest.raises(SnapshotError) as refused:
                snapshot.code_of(typed)
        finally:
            os.chmod(parent, stat.S_IRWXU)
        assert str(refused.value) == (
            f"{typed} is not under {directory}, which is the top of its repository as git gives it, so where the "
            f"folder is in its repository cannot be told"
        )
        assert snapshot.code_of(typed).subdirectory == ""  # and listed again, it is the folder


class TestWhatGitPrintedIsTakenWhole:
    @pytest.mark.skipif(os.name == "nt", reason="Windows takes a space off the end of a name")
    def test_a_repository_whose_folders_name_ends_in_a_space_is_placed(self, work):
        """Found by review: git's answer was stripped of every space around it, so the top of ``mono `` was ``mono``, a folder that is not there, and the pipeline was "not under" it. Only the line end is cut off."""
        mono = _committed(_folder(work / "mono " / "pipe").parent)
        code = snapshot.code_of(mono / "pipe")
        assert (str(code.top), code.subdirectory) == (str(work / "mono "), "pipe")
        assert snapshot.code_of(mono).subdirectory == ""
