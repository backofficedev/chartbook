import importlib.resources
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from chartbook import markdown_generator
from chartbook.diagnostics import generate_metadata_diagnostics
from chartbook.errors import ValidationError, handle_validation_error
from chartbook.manifest import get_favicon_path, get_logo_path, load_manifest
from chartbook.utils import shutil
from chartbook.validation import validate_conf_py_values


def get_docs_src_path(pipeline_theme: str = "pipeline"):
    """Get the path to the docs_src directory included in the package."""
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
):
    """Run the pipeline publish script to generate markdown files.

    Args:
        docs_dir: Directory containing documentation source files
        project_dir: Root directory of the project
        pipeline_theme: Theme to use for pipeline documentation
        publish_dir: Directory where files will be published
        _docs_dir: Directory where documentation will be built
        size_threshold: File size threshold in MB above which to use memory-efficient loading
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
    )


def run_sphinx_build(_docs_dir: Path):
    """Run sphinx-build to generate HTML files."""
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


def generate_docs(
    output_dir: Path,
    project_dir: Path,
    publish_dir: Path = Path("./_output/to_be_published/"),
    _docs_dir: Path = Path("./_docs"),
    keep_build_dirs: bool = False,
    temp_docs_src_dir: Path = Path("_docs_src"),
    should_remove_existing: bool = False,
    size_threshold: float = 50,
):
    """Generate documentation by running both pipeline publish and sphinx build.

    Args:
        output_dir: Directory where output will be generated
        project_dir: Root directory of the project
        publish_dir: Directory where files will be published
        _docs_dir: Directory where documentation will be built
        keep_build_dirs: If True, keeps temporary build directory after generation
        should_remove_existing: If True, removes existing output directory after successful generation
        size_threshold: File size threshold in MB above which to use memory-efficient loading
    """

    output_dir = Path(output_dir).resolve()
    publish_dir = Path(publish_dir).resolve()
    _docs_dir = Path(_docs_dir).resolve()
    temp_docs_src_dir = Path(temp_docs_src_dir).resolve()

    # Load configuration
    manifest = load_manifest(project_dir)
    pipeline_theme = manifest["config"]["type"]

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
        )

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
    """Copy documentation source files and setup directory structure."""
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
