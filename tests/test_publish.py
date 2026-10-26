"""`chartbook publish`: a pipeline's publishable files, staged into a directory, from wherever it is run."""

import json
from pathlib import Path

import tomli
import tomli_w
from click.testing import CliRunner

from chartbook.cli import main
from chartbook.publish import publish_pipeline
from tests.fixtures import create_pipeline_project

NOTEBOOK = json.dumps({"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5})


def _project_with_notebooks(root: Path) -> Path:
    """A pipeline with two notebooks, one publishable, one not."""
    project = create_pipeline_project(root / "proj", pipeline_id="rates")
    (project / "notebooks").mkdir()
    for name in ("explore", "scratch"):
        (project / "notebooks" / f"{name}.ipynb").write_text(NOTEBOOK, encoding="utf-8")
    manifest = tomli.loads((project / "chartbook.toml").read_text(encoding="utf-8"))
    manifest["notebooks"] = {
        "explore": {"path": "notebooks/explore.ipynb", "docs": "Shown.", "publishable": True},
        "scratch": {"path": "notebooks/scratch.ipynb", "docs": "Kept back.", "publishable": False},
    }
    (project / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8")
    return project


def _is_the_revised_manifest(published: Path, project: Path) -> None:
    """The published chartbook.toml is the manifest as revised for publishing, not the copy."""
    assert published.read_bytes() != (project / "chartbook.toml").read_bytes()
    revised = tomli.loads(published.read_text(encoding="utf-8"))
    assert revised["project"]["name"] == "Test Pipeline"
    assert list(revised["notebooks"]) == ["explore"]
    assert "base_dir" not in revised and "pipeline_base_dir" not in revised
    assert not any(key.startswith("_") for key in revised["dataframes"]["dataframe_0"])


class TestPublishFromAnotherDirectory:
    def test_publish_pipeline_revises_the_manifest_it_copied(self, tmp_path, monkeypatch):
        """Found by a reviewer: the manifest was revised from the working directory, not the
        project, so `chartbook publish --project-dir X` run from a folder with no chartbook.toml
        raised FileNotFoundError after the README, manifest and dodo.py were already staged."""
        project = _project_with_notebooks(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        publish_dir = tmp_path / "out"

        publish_pipeline(publish_dir=publish_dir, base_dir=project)

        assert not (elsewhere / "chartbook.toml").exists()
        assert (publish_dir / "README.md").is_file() and (publish_dir / "dodo.py").is_file()
        assert (publish_dir / "notebooks" / "explore.ipynb").is_file()
        assert not (publish_dir / "notebooks" / "scratch.ipynb").exists()
        _is_the_revised_manifest(publish_dir / "chartbook.toml", project)

    def test_the_command_takes_its_project_dir_from_anywhere(self, tmp_path, monkeypatch):
        project = _project_with_notebooks(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        publish_dir = tmp_path / "staged"

        result = CliRunner().invoke(main, ["publish", "--project-dir", str(project), "--publish-dir", str(publish_dir)])

        assert result.exit_code == 0, result.output
        staged = publish_dir / "rates"  # under the pipeline's ID
        assert (staged / "README.md").is_file()
        _is_the_revised_manifest(staged / "chartbook.toml", project)

    def test_the_module_has_no_default_taken_from_the_working_directory(self):
        """A default read at import time was the working directory of whatever imported the
        module; a publish says where its project and its destination are, every time."""
        import inspect

        from chartbook import publish

        assert not hasattr(publish, "BASE_DIR") and not hasattr(publish, "PUBLISH_DIR")
        for function in (publish.revise_published_chartbook_toml, publish.get_pipeline_publishing_plan, publish.create_dodo_file_with_mod_date):
            for name in ("base_dir", "publish_dir"):
                parameter = inspect.signature(function).parameters.get(name)
                assert parameter is None or parameter.default is inspect.Parameter.empty, (function.__name__, name)
