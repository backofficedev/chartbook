"""Tests for ``[scripts]`` and ``chartbook run``: ``chartbook.run``.

This is the first part of step 4 of ``docs_src/design/overview.md``. A
pipeline names its commands, and ``chartbook run`` runs one of them in the
pipelines it depends on, in order, and then in it. Nothing is skipped yet.

The scripts here are one-line shell commands that leave a file behind, so
a test can see what ran, where and in what order.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import index, lock, run
from chartbook.cli import main
from chartbook.gitcache import GitCache
from chartbook.manifest import load_manifest, read_scripts
from chartbook.run import RunError, Step, execute, plan
from chartbook.store import default_store

posix = pytest.mark.skipif(os.name == "nt", reason="the scripts here are POSIX shell")

# Appends the pipeline's name to one shared file, so the order can be read back
LOG = 'echo "$(basename "$PWD")" >> ../order.log'


def _pipeline(directory: Path, scripts=None, dependencies=None, **tables) -> Path:
    table = {"project": {"id": directory.name}, **tables}
    if scripts is not None:
        table["scripts"] = scripts
    if dependencies is not None:
        table["dependencies"] = dependencies
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table))
    return directory


def _order(work: Path) -> list:
    log = work / "order.log"
    return log.read_text().split() if log.exists() else []


def _git(directory: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def chain(work):
    """``top`` depends on ``middle``, which depends on ``bottom``. Each logs its name."""
    _pipeline(work / "bottom", {"build": LOG})
    _pipeline(work / "middle", {"build": LOG}, {"bottom": {"path": "../bottom"}})
    return _pipeline(work / "top", {"build": LOG}, {"middle": {"path": "../middle"}})


class TestScripts:
    """``[scripts]`` as the manifest loader reads it."""

    def test_named_commands(self):
        raw = {"scripts": {"build": "doit", "test": "pytest", "fetch.wrds": "python pull.py"}}
        assert read_scripts(raw) == raw["scripts"]

    def test_none(self):
        assert read_scripts({}) == {}
        assert read_scripts({"scripts": {}}) == {}

    def test_the_build_field_of_the_project_table_is_the_build_script(self):
        assert read_scripts({"project": {"build": "doit"}}) == {"build": "doit"}
        both = {"project": {"build": "doit"}, "scripts": {"build": "doit", "test": "pytest"}}
        assert read_scripts(both) == {"build": "doit", "test": "pytest"}

    def test_given_twice_and_differently_is_refused(self):
        raw = {"project": {"build": "make"}, "scripts": {"build": "doit"}}
        with pytest.raises(ValueError, match="given twice, and differently"):
            read_scripts(raw)

    @pytest.mark.parametrize(
        "scripts, message",
        [
            ("doit", "must be a table of named commands"),
            ({"build": ""}, "'build' must be a command"),
            ({"build": ["doit"]}, "'build' must be a command"),
            ({"build": {"cmd": "doit"}}, "'build' must be a command"),
            ({"my build": "doit"}, "is not a name a script can have"),
            ({"a/b": "doit"}, "is not a name a script can have"),
            ({"": "doit"}, "is not a name a script can have"),
        ],
    )
    def test_a_malformed_table_is_refused(self, scripts, message):
        with pytest.raises(ValueError, match=message):
            read_scripts({"scripts": scripts})

    def test_a_script_of_several_lines_is_kept_whole(self):
        script = "module load python\npython src/pull.py\n"
        assert read_scripts({"scripts": {"fetch": script}})["fetch"] == script

    def test_the_loaded_manifest_has_one_build_script_wherever_it_was_written(self, work):
        new_place = load_manifest(_pipeline(work / "a", {"build": "doit", "test": "pytest"}))
        assert new_place["scripts"] == {"build": "doit", "test": "pytest"}
        # Pages and the policy read it from the project table
        assert new_place["project"]["build"] == "doit"

        old_place = _pipeline(work / "b")
        (old_place / "chartbook.toml").write_text('[project]\nid = "b"\nbuild = "make"\n')
        loaded = load_manifest(old_place)
        assert loaded["scripts"] == {"build": "make"} and loaded["project"]["build"] == "make"
        assert "scripts" not in load_manifest(_pipeline(work / "c"))

    def test_an_error_names_the_file(self, work):
        directory = _pipeline(work / "a", {"build": ""})
        with pytest.raises(ValueError) as e:
            load_manifest(directory)
        assert str(directory / "chartbook.toml") in str(e.value)

    def test_a_catalog_has_none(self, work):
        _pipeline(work / "p", {"build": "doit"})
        (work / "chartbook.toml").write_text(
            tomli_w.dumps(
                {
                    "project": {"type": "catalog"},
                    "pipelines": {"p": {"path": "p"}},
                    "scripts": {"build": "doit"},
                }
            )
        )
        with pytest.raises(ValueError, match=r"a catalog has no \[scripts\]"):
            load_manifest(work)

    def test_the_index_lists_them(self, work):
        built = index.build_index(load_manifest(_pipeline(work / "a", {"test": "pytest", "build": "doit"})))
        assert built["records"][0]["scripts"] == {"build": "doit", "test": "pytest"}
        assert list(built["records"][0]["scripts"]) == ["build", "test"]
        bare = index.build_index(load_manifest(_pipeline(work / "b")))
        assert "scripts" not in bare["records"][0]


class TestPlan:
    def test_a_pipeline_alone(self, work):
        directory = _pipeline(work / "alone", {"build": "doit"})
        assert plan(directory) == [
            Step("alone", directory, "asked", {"build": "doit"}, has_dependencies=False)
        ]

    def test_dependencies_come_first(self, chain, work):
        steps = plan(chain)
        assert [step.id for step in steps] == ["bottom", "middle", "top"]
        assert [step.source for step in steps] == ["path", "path", "asked"]
        assert [step.has_dependencies for step in steps] == [False, True, True]
        assert steps[0].directory == work / "bottom"

    def test_a_pipeline_two_others_depend_on_is_there_once(self, work):
        _pipeline(work / "shared", {"build": LOG})
        _pipeline(work / "left", {"build": LOG}, {"shared": {"path": "../shared"}})
        _pipeline(work / "right", {"build": LOG}, {"shared": {"path": "../shared"}})
        top = _pipeline(
            work / "top",
            {"build": LOG},
            {"left": {"path": "../left"}, "right": {"path": "../right"}},
        )
        assert [step.id for step in plan(top)] == ["shared", "left", "right", "top"]

    def test_the_name_is_the_pipelines_own_not_the_key_it_is_declared_under(self, work):
        _pipeline(work / "rates", {"build": LOG})
        top = _pipeline(work / "top", {"build": LOG}, {"acme/upstream": {"path": "../rates"}})
        assert [step.id for step in plan(top)] == ["rates", "top"]

    def test_pipelines_that_depend_on_each_other_have_no_order(self, work):
        _pipeline(work / "a", {"build": LOG}, {"b": {"path": "../b"}})
        _pipeline(work / "b", {"build": LOG}, {"a": {"path": "../a"}})
        with pytest.raises(RunError, match="depend on each other") as e:
            plan(work / "a")
        assert f"{work / 'a'} -> {work / 'b'} -> {work / 'a'}" in str(e.value)

    def test_a_dependency_that_is_not_here_is_marked_and_kept_in_the_order(self, work):
        top = _pipeline(work / "top", {"build": LOG}, {"gone": {"path": "../gone"}})
        missing, itself = plan(top)
        assert missing == Step("gone", None, "path", missing=f"no pipeline at {work / 'gone'}")
        assert itself.id == "top"

    def test_a_catalog_is_all_its_pipelines(self, chain, work):
        _pipeline(work / "apart", {"build": LOG})
        (work / "chartbook.toml").write_text(
            tomli_w.dumps(
                {
                    "project": {"type": "catalog"},
                    "pipelines": {"top": {"path": "top"}, "apart": {"path": "apart"}},
                }
            )
        )
        steps = plan(work)
        # In the order the catalog lists them, each after what it depends on
        assert [step.id for step in steps] == ["bottom", "middle", "top", "apart"]
        # A catalog's members were asked for; what they depend on was not
        assert [step.source for step in steps] == ["path", "path", "asked", "asked"]

    def test_a_manifest_that_cannot_be_read_names_the_file(self, work):
        """Several are read in one run, so the error says which."""
        bad = _pipeline(work / "bad")
        (bad / "chartbook.toml").write_text("this is not toml\n")
        top = _pipeline(work / "top", {"build": LOG}, {"bad": {"path": "../bad"}})
        with pytest.raises(ValueError) as e:
            plan(top)
        assert str(bad / "chartbook.toml") in str(e.value)

    def test_no_manifest(self, work):
        with pytest.raises(RunError, match="No chartbook.toml in"):
            plan(work)

    def test_a_malformed_table_names_the_file(self, work):
        directory = _pipeline(work / "a", {"build": "doit"}, {"x": "../x"})
        with pytest.raises(ValueError) as e:
            plan(directory)
        assert str(directory / "chartbook.toml") in str(e.value)


@posix
class TestExecute:
    def test_it_runs_in_the_pipelines_directory(self, work):
        assert execute("pwd > here.txt", work) == 0
        assert Path((work / "here.txt").read_text().strip()).resolve() == work

    def test_several_lines_are_one_script(self, work):
        """What one line sets up, the next can use."""
        script = "NAME=rates\ncd .\necho $NAME > name.txt\n"
        assert execute(script, work) == 0
        assert (work / "name.txt").read_text().strip() == "rates"

    def test_it_stops_at_the_first_command_that_fails(self, work):
        code = execute("echo one > one.txt\nfalse\necho two > two.txt\n", work)
        assert code != 0
        assert (work / "one.txt").exists() and not (work / "two.txt").exists()

    def test_the_exit_code_is_the_scripts(self, work):
        assert execute("exit 7", work) == 7

    def test_a_script_a_signal_stopped_is_a_failure_the_way_a_shell_reports_it(self, work):
        assert execute("kill -TERM $$", work) == 128 + 15

    def test_what_was_said_before_it_is_out_before_it_speaks(self, work):
        """In a log, the line that names a pipeline comes before its output."""
        program = (
            "from chartbook.run import execute\n"
            "print('before')\n"
            "execute('echo during', '.')\n"
            "print('after')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", program], cwd=work, capture_output=True, text=True
        )
        assert result.stdout.split() == ["before", "during", "after"], result.stderr


@posix
class TestRun:
    def test_the_script_runs_in_each_pipeline_dependencies_first(self, chain, work):
        report = run.run(chain, echo=lambda line: None)
        assert _order(work) == ["bottom", "middle", "top"]
        assert [step.id for step in report.ran] == ["bottom", "middle", "top"]
        assert report.failed is None and report.exit_code == 0 and report.script == "build"

    def test_it_says_what_it_is_doing(self, chain, work):
        said = []
        run.run(chain, echo=said.append)
        assert said == [
            f"bottom: build    in {work / 'bottom'}",
            f"middle: build    in {work / 'middle'}",
            "top: build",
        ]

    def test_every_script_runs_every_time(self, chain, work):
        """Nothing is skipped yet. The pipeline's own tool skips what it can."""
        run.run(chain, echo=lambda line: None)
        run.run(chain, echo=lambda line: None)
        assert _order(work) == ["bottom", "middle", "top"] * 2

    def test_the_first_failure_stops_the_run(self, work):
        _pipeline(work / "bottom", {"build": LOG})
        _pipeline(work / "middle", {"build": "exit 3"}, {"bottom": {"path": "../bottom"}})
        top = _pipeline(work / "top", {"build": LOG}, {"middle": {"path": "../middle"}})
        report = run.run(top, echo=lambda line: None)
        assert report.failed.id == "middle" and report.exit_code == 3
        assert report.reason == "its 'build' script exited with 3"
        assert [step.id for step in report.ran] == ["bottom"]
        assert _order(work) == ["bottom"]  # and top was never run

    def test_another_script_by_name(self, work):
        _pipeline(work / "bottom", {"build": LOG, "test": LOG})
        _pipeline(work / "middle", {"build": LOG}, {"bottom": {"path": "../bottom"}})
        top = _pipeline(work / "top", {"build": LOG, "test": LOG}, {"middle": {"path": "../middle"}})
        said = []
        report = run.run(top, "test", echo=said.append)
        assert _order(work) == ["bottom", "top"]
        assert [(step.id, why) for step, why in report.skipped] == [
            ("middle", "it has no script named 'test'")
        ]
        assert "middle: not run. It has no script named 'test'." in said

    def test_the_pipeline_asked_for_must_have_the_script(self, chain, work):
        with pytest.raises(RunError) as e:
            run.run(chain, "test")
        assert "top has no script named 'test'. Its scripts are: build." in str(e.value)
        assert 'put the command under [scripts] in chartbook.toml: test = "…".' in str(e.value)
        assert _order(work) == []  # found out before anything was run

    def test_a_dependency_without_the_script_is_passed_over(self, work):
        _pipeline(work / "data_only")
        top = _pipeline(work / "top", {"build": LOG}, {"data_only": {"path": "../data_only"}})
        report = run.run(top, echo=lambda line: None)
        assert [step.id for step in report.ran] == ["top"]
        assert [step.id for step, _ in report.skipped] == ["data_only"]

    def test_a_catalog_runs_all_its_pipelines(self, chain, work):
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {"top": {"path": "top"}}})
        )
        said = []
        run.run(work, echo=said.append)
        assert _order(work) == ["bottom", "middle", "top"]
        # None of them is where the command was given, so each says where it is
        assert said[-1] == f"top: build    in {work / 'top'}"

    def test_a_catalog_passes_over_a_pipeline_without_the_script(self, chain, work):
        _pipeline(work / "apart", {"build": LOG, "test": LOG})
        (work / "chartbook.toml").write_text(
            tomli_w.dumps(
                {
                    "project": {"type": "catalog"},
                    "pipelines": {"top": {"path": "top"}, "apart": {"path": "apart"}},
                }
            )
        )
        report = run.run(work, "test", echo=lambda line: None)
        assert [step.id for step in report.ran] == ["apart"]
        assert [step.id for step, _ in report.skipped] == ["bottom", "middle", "top"]

    def test_a_script_nobody_has(self, chain, work):
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {"top": {"path": "top"}}})
        )
        with pytest.raises(RunError, match="No pipeline here has a script named 'deploy'"):
            run.run(work, "deploy")


@pytest.fixture
def reader(work):
    """``upstream`` builds a dataframe; ``reader`` copies its pinned copy.

    The upstream's build writes something new every time it runs, as a
    pipeline that pulls live data does.
    """
    _pipeline(
        work / "upstream",
        {"build": "mkdir -p _data && date +%s%N > _data/x.parquet && echo run >> _data/x.parquet && cat _data/x.parquet >> ../upstream_runs.log"},
        dataframes={"x": {"path": "./_data/x.parquet", "docs": "d"}},
    )
    chartbook = Path(sys.executable).with_name("chartbook")
    return _pipeline(
        work / "reader",
        {"build": f"mkdir -p _output && cat $({chartbook} path upstream:x) > _output/read.txt"},
        {"upstream": {"path": "../upstream"}},
    )


@posix
class TestPinning:
    def test_what_a_pipeline_depends_on_is_pinned_before_it_is_built(self, reader, work):
        """So that its code can read it: here, with `chartbook path upstream:x`."""
        pinned = []
        report = run.run(reader, echo=lambda line: None, on_pin=lambda step, pins: pinned.append((step.id, pins)))
        assert report.failed is None, report.reason
        assert [name for name, _ in pinned] == ["reader"]
        assert {e.status for e in pinned[0][1].events} == {"pinned"}
        # It read what the upstream had just built
        assert (reader / "_output" / "read.txt").read_text() == (
            work / "upstream" / "_data" / "x.parquet"
        ).read_text()

    def test_run_never_moves_a_pin(self, reader, work):
        """The decision: the upstream is rebuilt, and this pipeline keeps its copy."""
        run.run(reader, echo=lambda line: None)
        first = (reader / "_output" / "read.txt").read_text()
        before = (reader / lock.LOCK_FILE).read_bytes()

        pinned = []
        run.run(reader, echo=lambda line: None, on_pin=lambda step, pins: pinned.append(pins))
        upstream_now = (work / "upstream" / "_data" / "x.parquet").read_text()
        assert upstream_now != first  # the upstream did rebuild
        assert (reader / "_output" / "read.txt").read_text() == first
        assert (reader / lock.LOCK_FILE).read_bytes() == before
        assert pinned[0].count("stale") == 1

        # `chartbook update` is what moves it
        lock.update(reader)
        run.run(reader, echo=lambda line: None)
        assert (reader / "_output" / "read.txt").read_text() != first

    def test_a_pipeline_with_nothing_to_run_is_not_pinned_for(self, work):
        """No script runs in it, so nothing in it needs a pin."""
        _pipeline(work / "bottom", {"build": LOG}, dataframes={"x": {"path": "./x.parquet", "docs": "d"}})
        (work / "bottom" / "x.parquet").write_bytes(b"x")
        middle = _pipeline(work / "middle", None, {"bottom": {"path": "../bottom"}})
        top = _pipeline(work / "top", {"build": LOG}, {"middle": {"path": "../middle"}})
        report = run.run(top, echo=lambda line: None)
        assert [step.id for step in report.ran] == ["bottom", "top"]
        assert not (middle / lock.LOCK_FILE).exists()
        assert (top / lock.LOCK_FILE).exists()

    def test_another_script_pins_nothing(self, work):
        _pipeline(work / "upstream", {"test": LOG}, dataframes={"x": {"path": "./x.parquet", "docs": "d"}})
        (work / "upstream" / "x.parquet").write_bytes(b"x")
        top = _pipeline(work / "top", {"build": LOG, "test": LOG}, {"upstream": {"path": "../upstream"}})
        run.run(top, "test", echo=lambda line: None)
        assert not (top / lock.LOCK_FILE).exists()

    def test_what_cannot_be_pinned_stops_the_run_before_the_build(self, work):
        top = _pipeline(work / "top", {"build": LOG}, {"gone": {"path": "../gone"}})
        said = []
        report = run.run(top, echo=said.append)
        assert report.failed.id == "top" and report.exit_code == 1
        assert report.reason == "what it depends on could not be pinned"
        assert said == [f"gone: not run. no pipeline at {work / 'gone'}"]
        assert _order(work) == []

    def test_a_dependency_that_has_gone_is_no_trouble_once_it_is_pinned(self, reader, work):
        run.run(reader, echo=lambda line: None)
        first = (reader / "_output" / "read.txt").read_text()
        os.rename(work / "upstream", work / "moved_away")
        report = run.run(reader, echo=lambda line: None)
        assert report.failed is None, report.reason
        assert [step.id for step in report.ran] == ["reader"]
        assert (reader / "_output" / "read.txt").read_text() == first


@posix
class TestGitDependencies:
    """``run`` builds a git dependency, in a writable copy of its checkout."""

    @pytest.fixture
    def repository(self, work):
        """A pipeline in git whose data is built, and git-ignored."""
        directory = _pipeline(
            work / "upstream",
            {"build": "mkdir -p _data && echo built-by-its-build > _data/built.parquet"},
            dataframes={
                "built": {"path": "./_data/built.parquet", "docs": "d"},
                "committed": {"path": "./data/committed.parquet", "docs": "d"},
            },
        )
        (directory / "data").mkdir()
        (directory / "data" / "committed.parquet").write_bytes(b"hello")
        (directory / ".gitignore").write_text("/_data/\n")
        _git(directory, "init", "--quiet", "-b", "main")
        _git(directory, "add", "-A")
        _git(directory, "commit", "--quiet", "-m", "A pipeline")
        return directory

    @pytest.fixture
    def downstream(self, work, repository):
        chartbook = Path(sys.executable).with_name("chartbook")
        return _pipeline(
            work / "downstream",
            {"build": f"mkdir -p _output && cat $({chartbook} path upstream:built) > _output/read.txt"},
            {"acme/upstream": {"git": "../upstream"}},
        )

    def test_pin_alone_has_only_what_the_repository_commits(self, downstream):
        report = lock.pin(downstream)
        statuses = {e.asset.split(":")[1]: e.status for e in report.events if e.asset}
        assert statuses == {"built": "not_built", "committed": "pinned"}

    def test_run_builds_it_and_then_its_built_data_can_be_pinned(self, downstream, repository, work):
        said = []
        report = run.run(downstream, echo=said.append)
        assert report.failed is None, report.reason
        assert [step.id for step in report.ran] == ["upstream", "downstream"]
        assert [step.source for step in report.ran] == ["git", "asked"]

        # It was built in a copy, never in the checkout and never in the repository
        commit = _git(repository, "rev-parse", "HEAD")
        cache = GitCache(os.environ["CHARTBOOK_GIT_CACHE"])
        copy = cache.find_work(str(repository), commit)
        assert said[0] == f"upstream: build    in {copy}"
        assert (copy / "_data" / "built.parquet").read_text() == "built-by-its-build\n"
        assert not (cache.find(str(repository), commit) / "_data").exists()
        assert not (repository / "_data").exists()

        # ...and the downstream read the pinned copy of what was built
        assert (downstream / "_output" / "read.txt").read_text() == "built-by-its-build\n"
        locked = lock.read_lock(downstream)
        assert locked.assets["acme/upstream:built"]["content_hash"].startswith("sha256:")
        path = subprocess.run(
            [str(Path(sys.executable).with_name("chartbook")), "path", "upstream:built"],
            cwd=downstream,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert default_store().root in Path(path).parents

    def test_run_stays_at_the_commit_that_is_pinned(self, downstream, repository, work):
        """The repository moves on; `run` builds what the lockfile names."""
        run.run(downstream, echo=lambda line: None)
        first = _git(repository, "rev-parse", "HEAD")
        (repository / "chartbook.toml").write_text(
            (repository / "chartbook.toml").read_text().replace(
                "built-by-its-build", "built-by-a-later-commit"
            )
        )
        _git(repository, "commit", "--quiet", "-am", "A new build")
        second = _git(repository, "rev-parse", "HEAD")
        cache = GitCache(os.environ["CHARTBOOK_GIT_CACHE"])

        report = run.run(downstream, echo=lambda line: None)
        assert report.failed is None, report.reason
        assert report.ran[0].directory == cache.work_path(str(repository), first)
        assert cache.find_work(str(repository), second) is None
        assert (downstream / "_output" / "read.txt").read_text() == "built-by-its-build\n"

        # `chartbook update` moves to the new commit. What was built at the
        # old one is let go: it did not come from the commit now named.
        moved = lock.update(downstream)
        statuses = {e.asset.split(":")[1]: e.status for e in moved.events if e.asset}
        assert statuses == {"built": "let_go", "committed": "kept"}
        locked = lock.read_lock(downstream)
        assert locked.dependencies[0]["location"]["commit"] == second
        assert "content_hash" not in locked.assets["acme/upstream:built"]

        # ...and `run` then builds that commit, and pins what it built
        report = run.run(downstream, echo=lambda line: None)
        assert report.failed is None, report.reason
        assert report.ran[0].directory == cache.work_path(str(repository), second)
        assert (downstream / "_output" / "read.txt").read_text() == "built-by-a-later-commit\n"

    def test_an_update_that_does_not_move_the_commit_keeps_what_was_built(self, downstream):
        """Only a new commit lets a built asset's pin go."""
        run.run(downstream, echo=lambda line: None)
        before = (downstream / lock.LOCK_FILE).read_bytes()
        again = lock.update(downstream)
        assert again.count("let_go") == 0
        assert (downstream / lock.LOCK_FILE).read_bytes() == before

    def test_update_says_what_it_let_go_and_what_to_do(self, downstream, repository, monkeypatch):
        run.run(downstream, echo=lambda line: None)
        (repository / "data" / "committed.parquet").write_bytes(b"hello again")
        _git(repository, "commit", "--quiet", "-am", "New data")
        monkeypatch.chdir(downstream)
        result = CliRunner().invoke(main, ["update"])
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert "acme/upstream: 1 moved, 1 let go" in lines
        assert "  let go: acme/upstream:built (./_data/built.parquet)" in lines
        assert (
            "  What was let go was built at the commit pinned before, and is not "
            "built at this one. `chartbook run` builds it and pins it."
        ) in lines

    def test_one_that_does_not_name_itself_goes_by_the_name_it_is_declared_under(self, work):
        """Its working copy's directory is named after a commit, which says nothing."""
        directory = work / "ref_data"
        directory.mkdir()
        (directory / "chartbook.toml").write_text('[scripts]\nbuild = "true"\n')
        _git(directory, "init", "--quiet", "-b", "main")
        _git(directory, "add", "-A")
        _git(directory, "commit", "--quiet", "-m", "A pipeline")
        top = _pipeline(work / "top", {"build": "true"}, {"acme/ref_data": {"git": "../ref_data"}})
        first, _ = plan(top)
        assert first.id == "acme/ref_data" and first.source == "git"
        assert first.directory.name == _git(directory, "rev-parse", "HEAD")

    def test_the_working_copy_is_writable_and_made_once(self, repository, work):
        cache = GitCache(work / "cache")
        checkout = cache.get(str(repository))
        copy = cache.work_copy(str(repository), checkout.commit)
        assert copy == cache.work_path(str(repository), checkout.commit)
        assert os.access(copy / "chartbook.toml", os.W_OK)
        assert not os.access(checkout.path / "chartbook.toml", os.W_OK)
        (copy / "marker").write_text("kept")
        assert cache.work_copy(str(repository), checkout.commit) == copy
        assert (copy / "marker").read_text() == "kept"
        assert cache.files(str(repository), checkout.commit) == copy
        with pytest.raises(ValueError, match="is not a full commit hash"):
            cache.work_path(str(repository), "abc")

    def test_a_repository_that_cannot_be_reached_is_marked(self, work):
        top = _pipeline(
            work / "top", {"build": LOG}, {"crsp": {"git": "https://user:s3cret@localhost:1/x.git"}}
        )
        missing, itself = plan(top)
        assert missing.id == "crsp" and missing.directory is None and missing.source == "git"
        assert missing.missing.startswith("could not fetch https://localhost:1/x.git: ")
        assert "s3cret" not in missing.missing


@posix
class TestCommand:
    def _run(self, *arguments):
        return CliRunner().invoke(main, ["run", *map(str, arguments)])

    def test_run(self, chain, work, monkeypatch):
        monkeypatch.chdir(chain)
        result = self._run()
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [
            f"bottom: build    in {work / 'bottom'}",
            f"middle: build    in {work / 'middle'}",
            "top: build",
            "Ran build in 3 pipeline(s).",
        ]
        assert _order(work) == ["bottom", "middle", "top"]

    def test_a_named_script_and_a_project_dir(self, work, monkeypatch):
        top = _pipeline(work / "top", {"build": LOG, "test": LOG})
        monkeypatch.chdir(work)
        result = self._run("test", "--project-dir", top)
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == ["top: test", "Ran test in 1 pipeline(s)."]

    def test_a_failing_script_gives_its_exit_code(self, work, monkeypatch):
        top = _pipeline(work / "top", {"build": "exit 5"})
        monkeypatch.chdir(top)
        result = self._run()
        assert result.exit_code == 5
        assert "Error: top: its 'build' script exited with 5. Nothing after it was run." in (
            result.output
        )

    def test_pins_are_reported_only_when_there_is_something_to_say(self, reader, monkeypatch):
        monkeypatch.chdir(reader)
        first = self._run()
        assert first.exit_code == 0, first.output
        assert "reader: pinning what it depends on" in first.output
        assert "upstream: 1 pinned" in first.output

        second = self._run()
        assert "upstream: 1 changed upstream since it was pinned" in second.output
        assert "1 pinned asset(s) have changed upstream. `chartbook update` moves the pins." in (
            second.output
        )

        CliRunner().invoke(main, ["update"])
        third = self._run()  # the upstream rebuilt again, so it is stale again
        assert "changed upstream" in third.output

    def test_an_unchanged_dependency_is_not_mentioned(self, work, monkeypatch):
        _pipeline(work / "upstream", {"build": "true"}, dataframes={"x": {"path": "./x.parquet", "docs": "d"}})
        (work / "upstream" / "x.parquet").write_bytes(b"x")
        top = _pipeline(work / "top", {"build": "true"}, {"upstream": {"path": "../upstream"}})
        monkeypatch.chdir(top)
        self._run()
        result = self._run()
        assert "pinning" not in result.output
        assert result.output.splitlines()[-1] == "Ran build in 2 pipeline(s)."

    def test_no_such_script_is_a_clean_error(self, chain, monkeypatch):
        monkeypatch.chdir(chain)
        result = self._run("deploy")
        assert result.exit_code == 1
        assert result.output.startswith("Error: top has no script named 'deploy'.")

    def test_pipelines_in_a_loop_are_a_clean_error(self, work, monkeypatch):
        _pipeline(work / "a", {"build": LOG}, {"b": {"path": "../b"}})
        _pipeline(work / "b", {"build": LOG}, {"a": {"path": "../a"}})
        monkeypatch.chdir(work / "a")
        result = self._run()
        assert result.exit_code == 1
        assert "depend on each other" in result.output

    def test_it_is_in_help(self):
        result = CliRunner().invoke(main, ["--help"])
        assert "run " in result.output
