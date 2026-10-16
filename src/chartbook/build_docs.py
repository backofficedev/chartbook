import importlib.resources
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

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
from chartbook.conf_validation import validate_conf_py_values, validate_source_files


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
    :param size_threshold: File size threshold in MB above which to use memory-efficient loading.
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

    result = subprocess.run(build_cmd, capture_output=True, text=True, check=False)
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
):
    """Write the complete Sphinx project for a site into a directory.

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

    # Render conf.py from Jinja2 template
    conf_template_path = sources_dir / "conf.py.j2"
    conf_output_path = sources_dir / "conf.py"

    env = Environment(
        loader=FileSystemLoader(sources_dir),
        undefined=StrictUndefined,
    )

    template = env.get_template("conf.py.j2")
    conf_content = template.render(site_config=site_config)

    with open(conf_output_path, "w") as f:
        f.write(conf_content)

    # Remove template file after rendering
    conf_template_path.unlink()


def generate_docs(
    output_dir: Path,
    project_dir: Path,
    publish_dir: Path = Path("./_output/to_be_published/"),
    _docs_dir: Path = Path("./_docs"),
    keep_build_dirs: bool = False,
    temp_docs_src_dir: Path = Path("_docs_src"),
    should_remove_existing: bool = False,
    size_threshold: float = 50,
    strict: bool = True,
    strip_mathjax2: bool = True,
    incremental: bool = False,
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
    :param size_threshold: File size threshold in MB above which to use memory-efficient loading.
    :type size_threshold: float
    :param strict: If True (default), error and exit when source files are missing.
        When False, affected pipelines are skipped with warnings.
    :type strict: bool
    :param strip_mathjax2: If True, strip Plotly's MathJax 2 scripts from notebook outputs
        to prevent conflicts with Sphinx's MathJax 3. Defaults to True.
    :type strip_mathjax2: bool
    :param incremental: If True, keep ``_docs_dir`` between builds and redo only
        what changed since the last one: pipelines whose inputs are unchanged are
        not regenerated, and Sphinx re-renders only pages whose source differs.
        The output directory is updated in place. Defaults to False, a clean build.
    :type incremental: bool
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
    missing_files = validate_source_files(manifest, project_dir)
    skip_pipelines: set[str] = set()
    if missing_files:
        error = MissingSourceFilesError(missing_files)
        if strict:
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
                    "left to build once it is skipped. Create the missing "
                    "files, or remove their entries from chartbook.toml.",
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
                "\"mkdocs\" is built whole. Run `chartbook docs` without them.",
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
        _write_sphinx_project(
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
        )

        # Run sphinx build
        run_sphinx_build(_docs_dir)

        # Copy build files to output
        html_build_dir = _docs_dir / "_build" / "html"
        if html_build_dir.exists():
            _install_site(html_build_dir, output_dir, should_remove_existing)
            _write_index(manifest, _docs_dir, output_dir, skip_pipelines, built=built, cache=cache)

    finally:
        if not keep_build_dirs:
            shutil.rmtree(_docs_dir, ignore_errors=True)
            shutil.rmtree(temp_docs_src_dir, ignore_errors=True)
        else:
            print(f"Keeping temporary build directory: {_docs_dir.resolve()}")


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
        _retrieve_correct_docs_src_dir(temp_docs_src_dir, manifest, project_dir, pipeline_theme)
        _check_policy(manifest, generate_metadata_diagnostics(manifest=manifest, docs_build_dir=pages_dir, skip_pipelines=skip_pipelines))
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
        (_docs_dir / "mkdocs.yml").write_text(yaml.safe_dump(configuration, sort_keys=False, allow_unicode=True), encoding="utf-8")
        run_mkdocs_build(_docs_dir)

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
        text=True,
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
            output_dir.mkdir(parents=True, exist_ok=True)
            output = incremental.sync_tree(
                html_build_dir,
                output_dir,
                preserve=[Path(".nojekyll"), Path(index.INDEX_FILE)],
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
