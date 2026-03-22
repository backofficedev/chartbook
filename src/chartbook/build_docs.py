import importlib.resources
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from chartbook import markdown_generator
from chartbook.diagnostics import generate_metadata_diagnostics
from chartbook.errors import MissingSourceFilesError, ValidationError, handle_validation_error
from chartbook.manifest import get_favicon_path, get_logo_path, load_manifest
from chartbook.utils import shutil
from chartbook.validation import validate_conf_py_values, validate_source_files


def get_docs_src_path(pipeline_theme: str = "pipeline"):
    """Get the path to the docs_src directory included in the package.

    :param pipeline_theme: Theme to use for pipeline documentation.
    :type pipeline_theme: str
    :returns: Path to the docs_src directory.
    :rtype: Path
    """
    package_path = importlib.resources.files("chartbook")
    if pipeline_theme == "pipeline":
        return Path(str(package_path)) / "docs_src_pipeline"
    elif pipeline_theme == "catalog":
        return Path(str(package_path)) / "docs_src_catalog"
    else:
        raise ValueError(f"Invalid pipeline theme: {pipeline_theme}")


def run_build_markdown(
    project_dir: Path,
    pipeline_theme: str = "catalog",
    publish_dir: Path = Path("./_output/to_be_published/"),
    _docs_dir: Path = Path("./_docs"),
    docs_src_dir: Path = Path("_docs_src"),
    size_threshold: float = 50,
    skip_pipelines: set[str] | None = None,
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
    """
    project_dir = Path(project_dir).resolve()
    publish_dir = Path(publish_dir).resolve()
    _docs_dir = Path(_docs_dir).resolve()
    docs_src_dir = Path(docs_src_dir).resolve()

    markdown_generator.build_all(
        docs_build_dir=_docs_dir,
        base_dir=project_dir,
        pipeline_theme=pipeline_theme,
        docs_src_dir=docs_src_dir,
        size_threshold=size_threshold,
        skip_pipelines=skip_pipelines,
    )


def run_sphinx_build(_docs_dir: Path):
    """Run sphinx-build to generate HTML files.

    :param _docs_dir: Directory where documentation is built.
    :type _docs_dir: Path
    :raises RuntimeError: If the sphinx-build command fails.
    """
    build_cmd = [
        "sphinx-build",
        "-M",
        "html",
        str(_docs_dir),
        str(_docs_dir / "_build"),
    ]

    result = subprocess.run(build_cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Sphinx build failed:\n{result.stderr}")


def _strip_mathjax2_from_notebooks(docs_dir: Path):
    """Strip MathJax 2 script tags from all notebooks in the build directory.

    :param docs_dir: The documentation build directory containing .ipynb files.
    :type docs_dir: Path
    """
    from chartbook.utils import strip_mathjax2_from_notebook

    for nb_path in docs_dir.rglob("*.ipynb"):
        strip_mathjax2_from_notebook(nb_path)


def generate_docs(
    output_dir: Path,
    project_dir: Path,
    publish_dir: Path = Path("./_output/to_be_published/"),
    _docs_dir: Path = Path("./_docs"),
    keep_build_dirs: bool = False,
    temp_docs_src_dir: Path = Path("_docs_src"),
    should_remove_existing: bool = False,
    size_threshold: float = 50,
    strict: bool = False,
    strip_mathjax2: bool = True,
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
    :param strict: If True, error and exit when source files are missing.
        When False (default), affected pipelines are skipped with warnings.
    :type strict: bool
    :param strip_mathjax2: If True, strip Plotly's MathJax 2 scripts from notebook outputs
        to prevent conflicts with Sphinx's MathJax 3. Defaults to True.
    :type strip_mathjax2: bool
    """

    output_dir = Path(output_dir).resolve()
    publish_dir = Path(publish_dir).resolve()
    _docs_dir = Path(_docs_dir).resolve()
    temp_docs_src_dir = Path(temp_docs_src_dir).resolve()

    # Load configuration
    manifest = load_manifest(project_dir)
    pipeline_theme = manifest["config"]["type"]

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

    # FULLY clean temp_docs_src_dir first
    if temp_docs_src_dir.exists():
        shutil.rmtree(temp_docs_src_dir)
    temp_docs_src_dir.mkdir(exist_ok=True)

    try:
        # Select the correct docs_src directory
        if pipeline_theme in ("pipeline", "catalog"):
            _retrieve_correct_docs_src_dir(
                temp_docs_src_dir, manifest, project_dir, pipeline_theme
            )
        else:
            raise ValueError(f"Invalid pipeline theme: {pipeline_theme}")

        # Generate diagnostics CSV first so it's available during markdown build
        generate_metadata_diagnostics(manifest=manifest, docs_build_dir=_docs_dir)

        # Run pipeline publish
        run_build_markdown(
            project_dir=project_dir,
            pipeline_theme=pipeline_theme,
            publish_dir=publish_dir,
            _docs_dir=_docs_dir,
            docs_src_dir=temp_docs_src_dir,
            size_threshold=size_threshold,
            skip_pipelines=skip_pipelines,
        )

        # Strip MathJax 2 from notebook outputs (prevents Plotly/Sphinx conflict)
        if strip_mathjax2:
            _strip_mathjax2_from_notebooks(_docs_dir)

        # Validate configuration values for conf.py
        try:
            site_config = validate_conf_py_values(manifest, pipeline_theme)
        except ValidationError as e:
            # Handle with user-friendly CLI output
            handle_validation_error(e, config_path=project_dir / "chartbook.toml")

        # Render conf.py from Jinja2 template
        conf_template_path = _docs_dir / "conf.py.j2"
        conf_output_path = _docs_dir / "conf.py"

        env = Environment(
            loader=FileSystemLoader(_docs_dir),
            undefined=StrictUndefined,
        )

        template = env.get_template("conf.py.j2")
        conf_content = template.render(site_config=site_config)

        with open(conf_output_path, "w") as f:
            f.write(conf_content)

        # Remove template file after rendering
        conf_template_path.unlink()

        # Run sphinx build
        run_sphinx_build(_docs_dir)

        # Copy build files to output
        html_build_dir = _docs_dir / "_build" / "html"
        if html_build_dir.exists():
            if should_remove_existing and output_dir.exists():
                # Use atomic replacement: copy to temp, remove old, rename temp
                import tempfile

                temp_output_dir = Path(tempfile.mkdtemp(prefix="chartbook_output_"))
                try:
                    shutil.copytree(html_build_dir, temp_output_dir, dirs_exist_ok=True)
                    (temp_output_dir / ".nojekyll").touch()

                    # Remove existing directory and replace with new one
                    shutil.rmtree(output_dir)
                    shutil.move(str(temp_output_dir), str(output_dir))
                except Exception:
                    # Clean up temp directory if something went wrong
                    if temp_output_dir.exists():
                        shutil.rmtree(temp_output_dir, ignore_errors=True)
                    raise
            else:
                # Standard copy operation for new directories
                output_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(html_build_dir, output_dir, dirs_exist_ok=True)
                (output_dir / ".nojekyll").touch()

    finally:
        if not keep_build_dirs:
            shutil.rmtree(_docs_dir, ignore_errors=True)
            shutil.rmtree(temp_docs_src_dir, ignore_errors=True)
        else:
            print(f"Keeping temporary build directory: {_docs_dir.resolve()}")


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
    docs_src_path = get_docs_src_path(pipeline_theme)
    for item in docs_src_path.glob("*"):
        dest = temp_docs_src_dir / item.name

        if item.is_file():
            shutil.copy(item, temp_docs_src_dir)
        elif item.is_dir():
            if dest.exists():
                shutil.rmtree(
                    dest, ignore_errors=True
                )  # manually delete first to avoid permission errors
            shutil.copytree(item, dest)

    (temp_docs_src_dir / "_static").mkdir(exist_ok=True)
    (temp_docs_src_dir / "assets").mkdir(exist_ok=True)

    logo_path = get_logo_path(manifest, project_dir)
    for dest_dir in ["_static", "assets"]:
        shutil.copy(logo_path, temp_docs_src_dir / dest_dir / "logo.png")

    favicon_path = get_favicon_path(manifest, project_dir)
    for dest_dir in ["_static", "assets"]:
        shutil.copy(favicon_path, temp_docs_src_dir / dest_dir / "favicon.ico")
