import importlib.resources
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from chartbook import hashing, index, sitefiles
from chartbook.diagnostics import generate_metadata_diagnostics
from chartbook.errors import MissingSourceFilesError, ValidationError, handle_validation_error
from chartbook.manifest import (
    get_favicon_path,
    get_logo_path,
    get_pipeline_manifest,
    load_manifest,
)
from chartbook.utils import copy_file, copy_tree, move_tree
from chartbook.writers import ASSISTANT_FILE
from chartbook.conf_validation import (
    OUTPUT_FILE_TYPES,
    built_nothing,
    validate_conf_py_values,
    validate_source_files,
)


def get_docs_src_path(pipeline_theme: str = "pipeline", writer: str = "sphinx"):
    """Get the path to the docs_src directory included in the package.

    :param pipeline_theme: Theme to use for pipeline documentation.
    :type pipeline_theme: str
    :param writer: The site tool, ``sphinx`` or ``mkdocs``; each has its own theme folders.
    :type writer: str
    :returns: Path to the docs_src directory.
    :rtype: Path
    """
    package_path = importlib.resources.files("chartbook")
    if pipeline_theme not in ("pipeline", "catalog"):
        raise ValueError(f"Invalid pipeline theme: {pipeline_theme}")
    if writer == "mkdocs":
        return Path(str(package_path)) / "docs_src_mkdocs" / pipeline_theme
    return Path(str(package_path)) / f"docs_src_{pipeline_theme}"


def run_build_markdown(
    project_dir: Path,
    pipeline_theme: str = "catalog",
    publish_dir: Path = Path("./_output/to_be_published/"),
    _docs_dir: Path = Path("./_docs"),
    docs_src_dir: Path = Path("_docs_src"),
    size_threshold: float = 50,
    skip_pipelines: set[str] | None = None,
    reuse_pipelines: set[str] | None = None,
    code_times: dict[str, str] | None = None,
    hash_cache=None,
    built_index: dict | None = None,
):
    """Run the pipeline publish script to generate markdown files.

    :param project_dir: Root directory of the project.
    :type project_dir: Path
    :param pipeline_theme: Theme to use for pipeline documentation.
    :type pipeline_theme: str
    :param publish_dir: Directory where files will be published.
    :type publish_dir: Path
    :param _docs_dir: Directory where documentation will be built.
    :type _docs_dir: Path
    :param docs_src_dir: Directory containing documentation source files.
    :type docs_src_dir: Path
    :param size_threshold: File size in MB above which a dataframe page does not read the file for its date range.
    :type size_threshold: float
    :param skip_pipelines: Set of pipeline IDs to skip due to missing files.
    :type skip_pipelines: set[str] | None
    :param reuse_pipelines: Set of pipeline IDs whose existing pages an
        incremental build is keeping, so they are not regenerated.
    :type reuse_pipelines: set[str] | None
    :param code_times: Code-change times already known, by pipeline ID.
    :type code_times: dict[str, str] | None
    """
    project_dir = Path(project_dir).resolve()
    publish_dir = Path(publish_dir).resolve()
    _docs_dir = Path(_docs_dir).resolve()
    docs_src_dir = Path(docs_src_dir).resolve()

    sitefiles.write_site(
        docs_build_dir=_docs_dir,
        base_dir=project_dir,
        pipeline_theme=pipeline_theme,
        docs_src_dir=docs_src_dir,
        size_threshold=size_threshold,
        skip_pipelines=skip_pipelines,
        reuse_pipelines=reuse_pipelines,
        code_times=code_times,
        hash_cache=hash_cache,
        built_index=built_index,
    )


def run_sphinx_build(_docs_dir: Path):
    """Run sphinx-build to generate HTML files.

    Sphinx keeps its cache under ``_docs_dir/_build``. When that directory
    survives from an earlier build, Sphinx re-reads only the source files
    that are newer than its cache and re-renders only their pages.

    :param _docs_dir: Directory where documentation is built.
    :type _docs_dir: Path
    :returns: What sphinx-build printed to standard output.
    :rtype: str
    :raises RuntimeError: If the sphinx-build command fails.
    """
    # The Sphinx installed alongside this interpreter, not whichever
    # sphinx-build happens to be first on PATH
    build_cmd = [
        sys.executable,
        "-m",
        "sphinx",
        "-M",
        "html",
        str(_docs_dir),
        str(_docs_dir / "_build"),
    ]

    result = subprocess.run(build_cmd, capture_output=True, text=True, check=False, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"Sphinx build failed:\n{result.stderr}")
    _echo_site_tool_warnings(result.stderr, "WARNING:")
    return result.stdout


def _strip_mathjax2_from_notebooks(docs_dir: Path):
    """Strip MathJax 2 script tags from all notebooks in the build directory.

    :param docs_dir: The documentation build directory containing .ipynb files.
    :type docs_dir: Path
    """
    from chartbook.utils import strip_mathjax2_from_notebook

    for nb_path in docs_dir.rglob("*.ipynb"):
        strip_mathjax2_from_notebook(nb_path)


def _write_sphinx_project(
    manifest: dict,
    project_dir: Path,
    pipeline_theme: str,
    sources_dir: Path,
    temp_docs_src_dir: Path,
    publish_dir: Path,
    size_threshold: float,
    strip_mathjax2: bool,
    skip_pipelines: set[str],
    reuse_pipelines: set[str] | None = None,
    code_times: dict[str, str] | None = None,
    hash_cache=None,
    built_index: dict | None = None,
    render_versions: bool = False,
):
    """Write the complete Sphinx project for a site into a directory.

    With *render_versions*, a catalog's versions are built after the policy
    check and before the pages, and what was built is returned.

    This is the first of the build's two stages: theme files, generated
    Markdown pages, copied charts and notebooks, the diagnostics CSV and a
    rendered ``conf.py``. The second stage is running Sphinx over the result.

    :param sources_dir: Where to write the project. A clean build writes
        straight into the Sphinx directory; an incremental build writes into
        a staging directory and syncs it across afterwards.
    :type sources_dir: Path
    :param reuse_pipelines: Pipelines whose pages are being kept from an
        earlier build and so are not written here.
    :type reuse_pipelines: set[str] | None
    """
    # Select the correct docs_src directory
    if pipeline_theme in ("pipeline", "catalog"):
        _retrieve_correct_docs_src_dir(
            temp_docs_src_dir, manifest, project_dir, pipeline_theme
        )
    else:
        raise ValueError(f"Invalid pipeline theme: {pipeline_theme}")

    # Generate diagnostics CSV first so it's available during markdown build
    diagnostic_rows = generate_metadata_diagnostics(
        manifest=manifest, docs_build_dir=sources_dir, skip_pipelines=skip_pipelines
    )

    # policy.mode = "strict" fails the build on any missing required
    # field. The policy is the catalog's, or a lone pipeline's own.
    _check_policy(manifest, diagnostic_rows)
    rendered = _render_versions(manifest, built_index) if render_versions and built_index is not None else None

    # Run pipeline publish
    run_build_markdown(
        project_dir=project_dir,
        pipeline_theme=pipeline_theme,
        publish_dir=publish_dir,
        _docs_dir=sources_dir,
        docs_src_dir=temp_docs_src_dir,
        size_threshold=size_threshold,
        skip_pipelines=skip_pipelines,
        reuse_pipelines=reuse_pipelines,
        code_times=code_times,
        hash_cache=hash_cache,
        built_index=built_index,
    )

    # Strip MathJax 2 from notebook outputs (prevents Plotly/Sphinx conflict)
    if strip_mathjax2:
        _strip_mathjax2_from_notebooks(sources_dir)

    # Validate configuration values for conf.py
    try:
        site_config = validate_conf_py_values(manifest, pipeline_theme)
    except ValidationError as e:
        # Handle with user-friendly CLI output
        handle_validation_error(e, config_path=project_dir / "chartbook.toml")

    # Render conf.py from the package's own template, never from the build
    # tree, where a site page could stand in for it and Sphinx runs conf.py
    from chartbook.config import untrusted_source

    conf_output_path = sources_dir / "conf.py"
    env = Environment(
        loader=FileSystemLoader(get_docs_src_path(pipeline_theme)),
        undefined=StrictUndefined,
    )
    conf_content = env.get_template("conf.py.j2").render(site_config=site_config)
    if untrusted_source():
        conf_content += _UNTRUSTED_CONF
        # No page takes in a file (include, literalinclude, csv-table)
        (sources_dir / "docutils.conf").write_text("[general]\nfile_insertion_enabled: false\n", encoding="utf-8", newline="\n")
    with open(conf_output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(conf_content)
    (sources_dir / "conf.py.j2").unlink(missing_ok=True)
    return rendered


#: Added to conf.py for a build of files from a store: a picture or a download
#: that names a file outside the site is not copied into it.
_UNTRUSTED_CONF = """

# A build of files laid out from a store (chartbook.config.untrusted_source):
# a picture or a download that names a file outside the site is dropped
def _chartbook_keep_inside(app, doctree):
    import os
    from docutils import nodes
    from sphinx import addnodes

    root = os.path.realpath(app.srcdir)
    here = os.path.dirname(os.path.realpath(app.env.doc2path(app.env.docname)))
    named = list(doctree.findall(nodes.image)) + list(doctree.findall(addnodes.download_reference))
    for node in named:
        targets = [str(node.get("uri") or node.get("reftarget") or "")]
        targets += [str(t) for t in (node.get("candidates") or {}).values()]
        for target in targets:
            if "://" in target or target.startswith("data:") or not target:
                continue
            # Sphinx reads a target that starts with / from the site's root
            base = root if target.startswith("/") else here
            full = os.path.realpath(os.path.join(base, target.lstrip("/")))
            if full != root and not full.startswith(root + os.sep):
                node.replace_self(nodes.literal(text=f"[{target}: outside the site, not included]"))
                break


def setup(app):
    app.connect("doctree-read", _chartbook_keep_inside, priority=100)
"""


def _missing_files_hint(manifest: dict, missing_files: list, after_build: bool) -> list[str] | None:
    """What to do about missing files, a line each, for the error that lists them.

    A catalog takes the error's own hint, which offers --no-strict. A lone
    pipeline has nothing left to build once it is skipped, so its hint never
    does: a missing output is made by the build script, unless that has
    just run. A version laid out from the store is as it was made: nothing
    is to be built or edited there, and the hint says only that.
    """
    from chartbook.config import untrusted_source

    if untrusted_source():
        # Its last line is what a catalog's link to the version says
        return ["This version's snapshot does not hold them."]
    if manifest["project"]["type"] != "pipeline":
        return None
    hint = ["Ensure these files exist or update the paths in chartbook.toml."]
    if any(missing.file_type in OUTPUT_FILE_TYPES for missing in missing_files):
        if after_build:
            hint.append(
                "The build script has just run and did not make the data, charts, notebooks or models listed."
            )
            hint.append(
                "A task the build tool does not run by default is not built: in a project made by "
                "`chartbook init`, `doit` runs the tasks defined above the `default_tasks` block "
                "at the end of dodo.py."
            )
        elif manifest["project"].get("build"):
            hint.append(
                "`chartbook build` runs the build script, which makes data, charts, notebooks "
                "and models, and then renders the site."
            )
    return hint


def _say_not_built_yet(manifest: dict, missing_files: list, project_dir: Path) -> None:
    """Say that the pipeline has built nothing yet, what the site shows instead, and what builds it.

    In a version laid out from the store, what is missing was not built in
    that version, and there is nothing to advise.
    """
    import click

    from chartbook.config import untrusted_source

    root = Path(project_dir).resolve()

    def shown(path: Path) -> str:
        try:
            return Path(path).relative_to(root).as_posix()
        except ValueError:
            return str(path)

    listed = [f"  - {missing.file_type}: {shown(missing.file_path)}" for missing in missing_files]
    if untrusted_source():
        click.echo(
            "\n".join(
                [f"{missing_files[0].pipeline_id}: not built in this version, so the site shows each as not built:"]
                + listed
            ),
            err=True,
        )
        return
    lines = [
        click.style("Warning: ", fg="yellow", bold=True)
        + f"{missing_files[0].pipeline_id} has built nothing it declares yet, so the site shows each as not built:"
    ]
    lines += listed
    if manifest["project"].get("build"):
        lines.append("`chartbook build` runs its build script and renders the site again.")
    else:
        lines.append("Build them, then run `chartbook docs generate` again.")
    lines.append("With --strict, this is an error.")
    click.echo("\n".join(lines), err=True)


def _refuse_unreadable(built: dict) -> None:
    """Stop on a declared output that is there and could not be read.

    The index has no hash for it, as for one that is not built, and warned
    when it tried. It is not "not built": the site would say so of a file
    that is there, so the build stops and names it.
    """
    from chartbook.sitefiles import not_built

    unreadable = [
        record
        for record in built.get("records", [])
        if record.get("kind") in ("Dataframe", "Chart", "Notebook", "Model")
        and (record.get("location") or {}).get("kind") == "file"
        and (record.get("location") or {}).get("resolved_path")
        and "content_hash" not in record
        and not not_built(record)
    ]
    if not unreadable:
        return
    import click

    lines = [click.style("Error: ", fg="red", bold=True) + "These files are there and could not be read:"]
    lines += [f"  - {record['id']}: {record['location']['resolved_path']}" for record in unreadable]
    lines.append("Make them readable, or rebuild them.")
    click.echo("\n".join(lines), err=True)
    raise SystemExit(1)


def generate_docs(
    output_dir: Path,
    project_dir: Path,
    publish_dir: Path = Path("./_output/to_be_published/"),
    _docs_dir: Path = Path("./_docs"),
    keep_build_dirs: bool = False,
    temp_docs_src_dir: Path = Path("_docs_src"),
    should_remove_existing: bool = False,
    size_threshold: float = 50,
    strict: Optional[bool] = None,
    strip_mathjax2: bool = True,
    incremental: bool = False,
    after_build: bool = False,
):
    """Generate documentation by running both pipeline publish and sphinx build.

    :param output_dir: Directory where output will be generated.
    :type output_dir: Path
    :param project_dir: Root directory of the project.
    :type project_dir: Path
    :param publish_dir: Directory where files will be published.
    :type publish_dir: Path
    :param _docs_dir: Directory where documentation will be built.
    :type _docs_dir: Path
    :param keep_build_dirs: If True, keeps temporary build directory after generation.
    :type keep_build_dirs: bool
    :param temp_docs_src_dir: Temporary directory for documentation source files.
    :type temp_docs_src_dir: Path
    :param should_remove_existing: If True, removes existing output directory after successful generation.
    :type should_remove_existing: bool
    :param size_threshold: File size in MB above which a dataframe page does not read the file for its date range.
    :type size_threshold: float
    :param strict: None (the default) errors and exits when source files are
        missing, except that a lone pipeline that has built none of its
        outputs yet (see :func:`chartbook.conf_validation.built_nothing`) is
        rendered, with a warning and each of them shown as not built. True,
        what ``--strict`` asks for, errors on that one too. False skips the
        pipelines that have missing files, with warnings, and renders a lone
        pipeline that has built nothing as None does.
    :type strict: bool | None
    :param strip_mathjax2: If True, strip Plotly's MathJax 2 scripts from notebook outputs
        to prevent conflicts with Sphinx's MathJax 3. Defaults to True.
    :type strip_mathjax2: bool
    :param incremental: If True, keep ``_docs_dir`` between builds and redo only
        what changed since the last one: pipelines whose inputs are unchanged are
        not regenerated, and Sphinx re-renders only pages whose source differs.
        The output directory is updated in place. Defaults to False, a clean build.
    :type incremental: bool
    :param after_build: True when the pipeline's build script has just run,
        as in ``chartbook build``. An output still missing then is one the
        build did not make, and is an error even when it is all of them.
    :type after_build: bool
    :returns: For an incremental build, a summary of what was redone. None otherwise.
    :rtype: IncrementalBuildSummary or None
    """

    output_dir = Path(output_dir).resolve()
    publish_dir = Path(publish_dir).resolve()
    _docs_dir = Path(_docs_dir).resolve()
    temp_docs_src_dir = Path(temp_docs_src_dir).resolve()

    # Load configuration
    manifest = load_manifest(project_dir)
    pipeline_theme = manifest["project"]["type"]

    # Validate that all source files exist
    from chartbook.config import untrusted_source

    missing_files = validate_source_files(manifest, project_dir)
    skip_pipelines: set[str] = set()
    if (
        missing_files
        and pipeline_theme == "pipeline"
        and strict is not True
        and not after_build
        and (
            built_nothing(manifest, missing_files)
            # A version laid out from the store holds what it built: the
            # rest was not built in that version, which is no mistake
            or (untrusted_source() and all(m.file_type in OUTPUT_FILE_TYPES for m in missing_files))
        )
    ):
        # Not built yet, as a new project or a fresh clone is: the site is
        # rendered all the same, with each output shown as not built
        _say_not_built_yet(manifest, missing_files, project_dir)
    elif missing_files:
        error = MissingSourceFilesError(
            missing_files, hint=_missing_files_hint(manifest, missing_files, after_build)
        )
        if strict is not False:
            # Raise error and exit
            error.exit_with_message()
        else:
            # Skip affected pipelines and continue
            skip_pipelines = error.get_pipelines_to_skip()
            import click
            for warning in error.format_skip_warnings():
                click.echo(click.style(warning, fg="yellow"), err=True)
            if pipeline_theme == "pipeline":
                # Skipping only helps a catalog, which has other pipelines
                # left to build. A pipeline on its own has nothing left.
                click.echo(
                    click.style("Error: ", fg="red", bold=True)
                    + "This project is a single pipeline, so there is nothing "
                    "left to build once it is skipped.\n"
                    + "\n".join(error.hint),
                    err=True,
                )
                raise SystemExit(1)

    writer = manifest["project"].get("writer", "sphinx")
    if writer == "mkdocs":
        if incremental:
            import click

            click.echo(
                click.style("Error: ", fg="red", bold=True)
                + "--incremental and --watch build with Sphinx; a site with [project] writer = "
                "\"mkdocs\" is built whole. Run `chartbook docs generate` without them.",
                err=True,
            )
            raise SystemExit(1)
        return _generate_docs_mkdocs(
            manifest=manifest,
            output_dir=output_dir,
            project_dir=project_dir,
            publish_dir=publish_dir,
            _docs_dir=_docs_dir,
            keep_build_dirs=keep_build_dirs,
            temp_docs_src_dir=temp_docs_src_dir,
            should_remove_existing=should_remove_existing,
            size_threshold=size_threshold,
            strip_mathjax2=strip_mathjax2,
            skip_pipelines=skip_pipelines,
        )

    if incremental:
        return _generate_docs_incremental(
            manifest=manifest,
            output_dir=output_dir,
            project_dir=project_dir,
            publish_dir=publish_dir,
            _docs_dir=_docs_dir,
            keep_build_dirs=keep_build_dirs,
            temp_docs_src_dir=temp_docs_src_dir,
            size_threshold=size_threshold,
            strip_mathjax2=strip_mathjax2,
            skip_pipelines=skip_pipelines,
        )

    # FULLY clean temp_docs_src_dir first
    if temp_docs_src_dir.exists():
        shutil.rmtree(temp_docs_src_dir)
    temp_docs_src_dir.mkdir(exist_ok=True)

    try:
        # The index first, once: the pages' provenance panels read it, and
        # it is written beside the site at the end. The code-change times
        # are worked out once here, for the index and then for the pages
        from chartbook.manifest import apply_code_change_times

        code_times = apply_code_change_times(manifest)
        _docs_dir.mkdir(parents=True, exist_ok=True)
        cache = hashing.HashCache(_docs_dir / hashing.CACHE_FILE)
        built = index.build_index(manifest, cache=cache, skip_pipelines=skip_pipelines)
        _refuse_unreadable(built)
        rendered = _write_sphinx_project(
            manifest=manifest,
            project_dir=project_dir,
            pipeline_theme=pipeline_theme,
            sources_dir=_docs_dir,
            temp_docs_src_dir=temp_docs_src_dir,
            publish_dir=publish_dir,
            size_threshold=size_threshold,
            strip_mathjax2=strip_mathjax2,
            skip_pipelines=skip_pipelines,
            code_times=code_times,
            hash_cache=cache,
            built_index=built,
            render_versions=True,
        )

        # Run sphinx build
        run_sphinx_build(_docs_dir)

        # Copy build files to output
        html_build_dir = _docs_dir / "_build" / "html"
        if html_build_dir.exists():
            _add_versions(manifest, built, html_build_dir, rendered)
            _install_site(html_build_dir, output_dir, should_remove_existing)
            _write_index(manifest, _docs_dir, output_dir, skip_pipelines, built=built, cache=cache)

    finally:
        if not keep_build_dirs:
            shutil.rmtree(_docs_dir, ignore_errors=True)
            shutil.rmtree(temp_docs_src_dir, ignore_errors=True)
        else:
            print(f"Keeping temporary build directory: {_docs_dir.resolve()}")


def _render_versions(manifest: dict, built: dict) -> Optional[dict]:
    """In a catalog, build each listed snapshot's site before the pages, so that they know which were built."""
    if manifest["project"]["type"] != "catalog":
        return None
    import click

    from chartbook import versions

    return versions.render_listed(
        built,
        echo=lambda line: click.echo(click.style("warning: ", fg="yellow") + line.removeprefix("warning: "), err=True),
    )


def _add_versions(manifest: dict, built: dict, html_build_dir: Path, rendered: Optional[dict] = None) -> None:
    """In a catalog, put each snapshot's own site into the rendered site, under ``versions/``."""
    if manifest["project"]["type"] != "catalog":
        return
    import click

    from chartbook import versions

    versions.add_to_site(
        built,
        html_build_dir,
        echo=lambda line: click.echo(click.style("warning: ", fg="yellow") + line.removeprefix("warning: "), err=True),
        rendered_by_moment=rendered,
    )


def _install_site(html_build_dir: Path, output_dir: Path, should_remove_existing: bool) -> None:
    """Put a rendered site in the output directory, whole or not at all when one is replaced."""
    if should_remove_existing and output_dir.exists():
        # Use atomic replacement: copy to temp, remove old, rename temp
        import tempfile

        temp_output_dir = Path(tempfile.mkdtemp(prefix="chartbook_output_"))
        try:
            copy_tree(html_build_dir, temp_output_dir)
            (temp_output_dir / ".nojekyll").touch()
            shutil.rmtree(output_dir)
            move_tree(temp_output_dir, output_dir)
        except Exception:
            if temp_output_dir.exists():
                shutil.rmtree(temp_output_dir, ignore_errors=True)
            raise
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        copy_tree(html_build_dir, output_dir)
        (output_dir / ".nojekyll").touch()


def _generate_docs_mkdocs(
    manifest: dict,
    output_dir: Path,
    project_dir: Path,
    publish_dir: Path,
    _docs_dir: Path,
    keep_build_dirs: bool,
    temp_docs_src_dir: Path,
    should_remove_existing: bool,
    size_threshold: float,
    strip_mathjax2: bool,
    skip_pipelines: set[str],
) -> None:
    """Build a site with MkDocs: the writer's pages under ``pages/``, ``mkdocs.yml`` beside them, then ``mkdocs build``.

    The same index, the same copied files and the same checks as the Sphinx
    build (:func:`_write_sphinx_project`), with the MkDocs writer's pages
    and its configuration in place of a Sphinx project and ``conf.py``.
    """
    import yaml

    from chartbook.manifest import apply_code_change_times
    from chartbook.writers import mkdocs as mkdocs_writer

    if not mkdocs_writer.is_installed():
        import click

        click.echo(
            click.style("Error: ", fg="red", bold=True)
            + f"this site is built with MkDocs ([project] writer = \"mkdocs\"), which is not installed: "
            f"pip install {mkdocs_writer.EXTRA}",
            err=True,
        )
        raise SystemExit(1)
    pipeline_theme = manifest["project"]["type"]
    if temp_docs_src_dir.exists():
        shutil.rmtree(temp_docs_src_dir)
    temp_docs_src_dir.mkdir(exist_ok=True)
    try:
        code_times = apply_code_change_times(manifest)
        pages_dir = _docs_dir / mkdocs_writer.PAGES_DIR
        pages_dir.mkdir(parents=True, exist_ok=True)
        cache = hashing.HashCache(_docs_dir / hashing.CACHE_FILE)
        built = index.build_index(manifest, cache=cache, skip_pipelines=skip_pipelines)
        _refuse_unreadable(built)
        _retrieve_correct_docs_src_dir(temp_docs_src_dir, manifest, project_dir, pipeline_theme)
        _check_policy(manifest, generate_metadata_diagnostics(manifest=manifest, docs_build_dir=pages_dir, skip_pipelines=skip_pipelines))
        rendered = _render_versions(manifest, built)
        run_build_markdown(
            project_dir=project_dir,
            pipeline_theme=pipeline_theme,
            publish_dir=publish_dir,
            _docs_dir=pages_dir,
            docs_src_dir=temp_docs_src_dir,
            size_threshold=size_threshold,
            skip_pipelines=skip_pipelines,
            code_times=code_times,
            hash_cache=cache,
            built_index=built,
        )
        if strip_mathjax2:
            _strip_mathjax2_from_notebooks(pages_dir)
        # The theme's second copy of the logo and favicon is for Sphinx's conf.py; Material shares that folder name
        shutil.rmtree(pages_dir / "assets", ignore_errors=True)
        _warn_about_sphinx_syntax_in_site_pages(built, pages_dir)
        try:
            site_config = validate_conf_py_values(manifest, pipeline_theme)
        except ValidationError as e:
            handle_validation_error(e, config_path=project_dir / "chartbook.toml")
        writer = mkdocs_writer.MkDocsWriter(built, theme=pipeline_theme, docs_src_dir=temp_docs_src_dir)
        configuration = writer.config(
            site_name=manifest["project"].get("name", ""),
            site_url=manifest["project"].get("site_url", ""),
            copyright=str(getattr(site_config, "copyright", "") or ""),
        )
        (_docs_dir / "mkdocs.yml").write_text(yaml.safe_dump(configuration, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
        run_mkdocs_build(_docs_dir)
        _add_versions(manifest, built, _docs_dir / "_build" / "html", rendered)

        _install_site(_docs_dir / "_build" / "html", output_dir, should_remove_existing)
        _write_index(manifest, _docs_dir, output_dir, skip_pipelines, built=built, cache=cache)
    finally:
        if not keep_build_dirs:
            shutil.rmtree(_docs_dir, ignore_errors=True)
            shutil.rmtree(temp_docs_src_dir, ignore_errors=True)
        else:
            print(f"Keeping temporary build directory: {_docs_dir.resolve()}")


def _warn_about_sphinx_syntax_in_site_pages(built: dict, pages_dir: Path) -> None:
    """Say which of a pipeline's own site pages carry a MyST fence, which MkDocs shows as code."""
    import click

    for record in built.get("records", []):
        if record.get("kind") != "Pipeline":
            continue
        for page in record.get("site_pages") or []:
            path = pages_dir / page
            if path.is_file() and "```{" in path.read_text(encoding="utf-8", errors="replace"):
                click.echo(
                    click.style("warning: ", fg="yellow")
                    + f"{page} uses Sphinx syntax (a ```{{...}} block), which MkDocs shows as code; "
                    f"this site is built with MkDocs ([project] writer = \"mkdocs\").",
                    err=True,
                )


def run_mkdocs_build(_docs_dir: Path) -> str:
    """Run ``mkdocs build`` over the project in ``_docs_dir``; the site lands in ``_build/html``.

    :raises RuntimeError: If MkDocs fails; its output is in the message.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "mkdocs", "build", "-f", str(_docs_dir / "mkdocs.yml")],
        capture_output=True,
        text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise RuntimeError(f"mkdocs build failed:\n{result.stdout}\n{result.stderr}")
    output = result.stdout + result.stderr
    _echo_site_tool_warnings(output, "WARNING")
    return output


def _echo_site_tool_warnings(output: str, prefix: str) -> None:
    """Print the site tool's warnings as the build's own ``warning:`` lines.

    Both tools say when a link on a page goes nowhere, and a build that
    swallowed that would hide a broken link scheme.
    """
    import click

    for line in output.splitlines():
        if line.startswith(prefix):
            click.echo(click.style("warning: ", fg="yellow") + line.removeprefix(prefix).lstrip(" -"), err=True)


def _check_policy(manifest: dict, diagnostic_rows) -> None:
    """``policy.mode = "strict"`` fails the build on any missing required field."""
    policy = manifest.get("policy")
    if policy and policy["mode"] == "strict":
        incomplete = [r for r in diagnostic_rows if not r.metadata_complete]
        if incomplete:
            import click

            lines = ["The policy is 'strict' and required metadata is missing:"]
            for row in incomplete:
                lines.append(
                    f"  - {row.object_type} '{row.pipeline_id}:{row.identifier}' missing: {row.missing_fields}"
                )
            lines.append(
                "Fill in the fields above, relax [policy.required], or set "
                "policy.mode = 'warn' in the chartbook.toml that sets the policy."
            )
            click.echo(click.style("\n".join(lines), fg="red"), err=True)
            raise SystemExit(1)


def _write_index(
    manifest: dict,
    _docs_dir: Path,
    output_dir: Path,
    skip_pipelines: set[str],
    built: dict | None = None,
    cache=None,
) -> None:
    """Write the build's index: everything the site contains, as one JSON file.

    The full index goes in the build directory. The published one, with no
    path that is specific to this machine, goes beside the HTML so that it
    travels with the site. File hashes are remembered in the build
    directory, so a kept one means unchanged files are not read again.

    See :mod:`chartbook.index`.
    """
    from chartbook import hashing, index

    if cache is None:
        cache = hashing.HashCache(_docs_dir / hashing.CACHE_FILE)
    if built is None:
        built = index.build_index(manifest, cache=cache, skip_pipelines=skip_pipelines)
    # An index that differs only in when it was generated is left alone, so
    # a build that changes nothing writes nothing.
    if _docs_dir.is_dir():
        cache.save()
        index.write_index(built, _docs_dir / index.INDEX_FILE, only_if_changed=True)
    index.write_index(
        index.published(built), output_dir / index.INDEX_FILE, only_if_changed=True
    )
    _write_assistant_file(manifest, built, output_dir)


def _write_assistant_file(manifest: dict, built: dict, output_dir: Path) -> None:
    """Write the site's assistant file beside its index: what is in the site and where, for a command-line agent.

    Written by the site's own writer, from the index (see
    :meth:`chartbook.writers.sphinx.SphinxWriter.assistant_file`); left
    alone when its text has not changed, as the index is.
    """
    from chartbook.writers import writer_class

    writer = writer_class(manifest["project"].get("writer", "sphinx"))(built, theme=manifest["project"]["type"])
    target = output_dir / writer.ASSISTANT_FILE
    text = writer.assistant_file()
    try:
        if target.read_text(encoding="utf-8") == text:
            return
    except OSError:
        pass
    target.write_text(text, encoding="utf-8", newline="\n")


@dataclass
class IncrementalBuildSummary:
    """What an incremental build redid.

    Attributes:
        fresh: True if the build tree was rebuilt from empty.
        reason: Why, when *fresh* is True.
        regenerated: Pipelines whose pages were generated.
        reused: Pipelines whose pages were kept from the previous build.
        sources_written: Files written into the Sphinx project because they
            were new or their content had changed.
        sources_deleted: Files removed from it because nothing produces them
            any more.
        rendered: Whether Sphinx was run. It is not when no source changed
            and the last render succeeded.
        pages_read: Source pages Sphinx re-read (added plus changed), or None
            if that could not be read from its output.
        output_written: Files written to the output directory.
    """

    fresh: bool
    reason: str
    regenerated: list[str]
    reused: list[str]
    sources_written: int
    sources_deleted: int
    rendered: bool
    pages_read: int | None
    output_written: int

    def describe(self) -> str:
        """One line for the console."""
        total = len(self.regenerated) + len(self.reused)
        if self.fresh:
            lead = f"Full build ({self.reason})"
        else:
            lead = "Incremental build"
        if not self.rendered:
            sphinx = "nothing to render"
        elif self.pages_read is None:
            sphinx = "Sphinx ran"
        else:
            sphinx = f"Sphinx re-read {self.pages_read} page(s)"
        return (
            f"{lead}: regenerated {len(self.regenerated)} of {total} pipeline(s); "
            f"{self.sources_written} source file(s) changed, "
            f"{self.sources_deleted} removed; {sphinx}."
        )


def _pages_sphinx_read(sphinx_output: str) -> int | None:
    """Count the source pages Sphinx re-read, from its "updating environment" line."""
    match = re.search(r"(\d+) added, (\d+) changed, (\d+) removed", sphinx_output or "")
    if match is None:
        return None
    return int(match.group(1)) + int(match.group(2))


def _generate_docs_incremental(
    manifest: dict,
    output_dir: Path,
    project_dir: Path,
    publish_dir: Path,
    _docs_dir: Path,
    keep_build_dirs: bool,
    temp_docs_src_dir: Path,
    size_threshold: float,
    strip_mathjax2: bool,
    skip_pipelines: set[str],
) -> IncrementalBuildSummary:
    """Build a site, redoing only what changed since the last incremental build.

    The Sphinx project in ``_docs_dir`` is kept. The pages of every pipeline
    whose inputs changed, and the site-wide pages, are generated into a
    staging directory and synced into it file by file; pipelines whose inputs
    did not change are left as they are. Sphinx then runs over the kept
    project with its cache intact, and the rendered site is synced to the
    output directory the same way.

    See :mod:`chartbook.incremental` for how "changed" is decided.
    """
    import tempfile

    from chartbook import hashing, incremental, index

    from chartbook import provenance
    from chartbook.manifest import get_pipeline_ids

    pipeline_theme = manifest["project"]["type"]
    options = {"size_threshold": size_threshold, "strip_mathjax2": strip_mathjax2}
    # A directory that is not a build tree is refused before any work is done
    incremental.check_build_tree(_docs_dir)
    # The index first, once. A pipeline's pages carry provenance panels that
    # read other pipelines' records, so whether its pages can be reused
    # depends on what those panels would say as well as on its own files
    cache = hashing.HashCache(_docs_dir / hashing.CACHE_FILE)
    built = index.build_index(manifest, cache=cache, skip_pipelines=skip_pipelines)
    _refuse_unreadable(built)
    rendered = _render_versions(manifest, built)
    records = {record["id"]: record for record in built["records"]}
    salts = {
        pipeline_id: provenance.digest(pipeline_id, records)
        for pipeline_id in get_pipeline_ids(manifest)
        if pipeline_id not in set(skip_pipelines)
    }
    plan = incremental.plan_build(
        manifest,
        build_dir=_docs_dir,
        theme_dir=get_docs_src_path(pipeline_theme),
        options=options,
        skip_pipelines=skip_pipelines,
        salts=salts,
    )
    incremental.prepare_build_tree(_docs_dir, fresh=plan.fresh)

    # When each pipeline's code changed. Asking git costs two calls per
    # pipeline, so the answer recorded for a reused pipeline is used again.
    from chartbook.manifest import CODE_TIME_FORMAT, find_latest_code_change

    for pipeline_id in plan.regenerate + plan.reuse:
        if pipeline_id not in plan.code_times:
            base_dir = get_pipeline_manifest(manifest, pipeline_id)["pipeline_base_dir"]
            plan.code_times[pipeline_id] = find_latest_code_change(base_dir).strftime(
                CODE_TIME_FORMAT
            )
    # The index was made before the plan; now that the times are known it
    # says when each pipeline's code last changed
    from chartbook.manifest import apply_code_change_times

    plan.code_times.update(apply_code_change_times(manifest, known=plan.code_times))
    index.apply_code_times(built, manifest)

    # FULLY clean temp_docs_src_dir first
    if temp_docs_src_dir.exists():
        shutil.rmtree(temp_docs_src_dir)
    temp_docs_src_dir.mkdir(exist_ok=True)

    try:
        with tempfile.TemporaryDirectory(prefix="chartbook_staging_") as staging:
            staging_dir = Path(staging)
            _write_sphinx_project(
                manifest=manifest,
                project_dir=project_dir,
                pipeline_theme=pipeline_theme,
                sources_dir=staging_dir,
                temp_docs_src_dir=temp_docs_src_dir,
                publish_dir=publish_dir,
                size_threshold=size_threshold,
                strip_mathjax2=strip_mathjax2,
                skip_pipelines=skip_pipelines,
                reuse_pipelines=set(plan.reuse),
                code_times=plan.code_times,
                # The build directory's hash cache, not one in the staging copy
                hash_cache=cache,
                built_index=built,
            )
            sources = incremental.sync_tree(
                staging_dir,
                _docs_dir,
                preserve=[
                    Path(incremental.SPHINX_BUILD_DIR),
                    Path(incremental.STATE_FILE),
                    Path(incremental.GITIGNORE_FILE),
                    Path(index.INDEX_FILE),
                    Path(hashing.CACHE_FILE),
                    *plan.preserved_paths(manifest),
                ],
            )
        html_build_dir = _docs_dir / incremental.SPHINX_BUILD_DIR / "html"
        sources_changed = bool(sources.written or sources.deleted)
        render = (
            sources_changed
            or not plan.rendered
            or not (html_build_dir / "index.html").is_file()
        )
        pages_read: int | None = 0
        if render:
            # The sources now reflect these inputs whether or not Sphinx
            # succeeds, so a failed render is retried without regenerating
            incremental.write_state(_docs_dir, plan, rendered=False)

            if sources.pages_added_or_removed and not plan.fresh:
                # Sphinx neither deletes the HTML of a page that is gone nor
                # redraws the navigation of pages that did not themselves
                # change. Dropping the rendered site makes it write every
                # page again from its cache, which stays, so nothing is
                # re-read to do it.
                shutil.rmtree(html_build_dir, ignore_errors=True)

            pages_read = _pages_sphinx_read(run_sphinx_build(_docs_dir))
        incremental.write_state(_docs_dir, plan, rendered=True)

        output_written = 0
        if html_build_dir.exists():
            _add_versions(manifest, built, html_build_dir, rendered)
            output_dir.mkdir(parents=True, exist_ok=True)
            output = incremental.sync_tree(
                html_build_dir,
                output_dir,
                preserve=[Path(".nojekyll"), Path(index.INDEX_FILE), Path(ASSISTANT_FILE)],
                same=incremental.same_size_and_not_newer,
            )
            (output_dir / ".nojekyll").touch()
            output_written = len(output.written)
            _write_index(manifest, _docs_dir, output_dir, skip_pipelines, built=built, cache=cache)
    finally:
        # The theme copy is rebuilt every time; only the Sphinx project is kept
        if not keep_build_dirs:
            shutil.rmtree(temp_docs_src_dir, ignore_errors=True)

    return IncrementalBuildSummary(
        fresh=plan.fresh,
        reason=plan.reason,
        regenerated=plan.regenerate,
        reused=plan.reuse,
        sources_written=len(sources.written),
        sources_deleted=len(sources.deleted),
        rendered=render,
        pages_read=pages_read,
        output_written=output_written,
    )


def _retrieve_correct_docs_src_dir(
    temp_docs_src_dir: Path,
    manifest: dict,
    project_dir: Path,
    pipeline_theme: str = "pipeline",
):
    """Copy documentation source files and setup directory structure.

    :param temp_docs_src_dir: Temporary directory for documentation source files.
    :type temp_docs_src_dir: Path
    :param manifest: The loaded manifest dictionary.
    :type manifest: dict
    :param project_dir: Root directory of the project.
    :type project_dir: Path
    :param pipeline_theme: Theme to use for pipeline documentation.
    :type pipeline_theme: str
    """
    docs_src_path = get_docs_src_path(pipeline_theme, manifest["project"].get("writer", "sphinx"))
    for item in docs_src_path.glob("*"):
        dest = temp_docs_src_dir / item.name

        if item.is_file():
            copy_file(item, temp_docs_src_dir / item.name)
        elif item.is_dir():
            if dest.exists():
                shutil.rmtree(
                    dest, ignore_errors=True
                )  # manually delete first to avoid permission errors
            copy_tree(item, dest)

    (temp_docs_src_dir / "_static").mkdir(exist_ok=True)
    (temp_docs_src_dir / "assets").mkdir(exist_ok=True)

    logo_path = get_logo_path(manifest, project_dir)
    for dest_dir in ["_static", "assets"]:
        copy_file(logo_path, temp_docs_src_dir / dest_dir / "logo.png")

    favicon_path = get_favicon_path(manifest, project_dir)
    for dest_dir in ["_static", "assets"]:
        copy_file(favicon_path, temp_docs_src_dir / dest_dir / "favicon.ico")
