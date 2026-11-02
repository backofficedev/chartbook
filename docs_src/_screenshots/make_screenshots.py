"""The documentation's screenshots, taken of a site ChartBook builds: one light and one dark file each.

Run from the repository root: ``python docs_src/_screenshots/make_screenshots.py``. It builds the
Quickstart's project (``docs_src/_examples/quickstart/``, the files the Quickstart page shows) in a
temporary folder, renders its site, and photographs pages of it with a headless Chrome or Edge.
The PNGs under ``docs_src/_static/screenshots/`` are what the pages show (``only-light`` /
``only-dark``); this script is how they are changed. Nothing imports it.

It needs the ChartBook of this checkout (``uv run python ...``) and Chrome or Edge installed;
``CHROME`` names the browser's executable where it is somewhere else. Nothing under ``~/.chartbook``
is read or written: the store, the cache and trust are pointed at the temporary folder.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

EXAMPLE = Path("docs_src/_examples/quickstart")
OUT = Path("docs_src/_static/screenshots")

#: Each screenshot: its name, the page, the window's size, and how many pixels of the top to cut
#: (the theme's header bar). 900 wide is narrow enough that the theme hides both sidebars.
SHOTS = [
    ("quickstart-site", "index.html", (1440, 900), 0),
    # The chart, its write-up and what it was made from, down to the hash it was made from
    ("quickstart-chart", "cb/charts/my_pipeline.random_walks.html", (900, 1255), 44),
    ("quickstart-dataframe", "cb/dataframes/my_pipeline/walks.html", (900, 1000), 44),
]

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
    "chromium-browser",
]


def browser() -> str:
    for candidate in [os.environ.get("CHROME"), *BROWSERS]:
        if candidate and (Path(candidate).is_file() or shutil.which(candidate)):
            return candidate
    sys.exit("No Chrome or Edge found: set CHROME to the browser's executable.")


def build(root: Path) -> Path:
    """The Quickstart's project, built as the page says, in a folder of *root*: its site's folder."""
    project = root / "my-pipeline"
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns("__pycache__", "_data", "_output", "docs"))
    env = {
        **os.environ,
        "CHARTBOOK_STORE": str(root / "home" / "store"),
        "CHARTBOOK_CACHE": str(root / "home" / "cache"),
        "CHARTBOOK_GIT_CACHE": str(root / "home" / "git"),
        "CHARTBOOK_SYSTEM_SETTINGS": str(root / "home" / "system-settings.toml"),
        # The Quickstart answers y when asked; this answers it without recording anything
        "CHARTBOOK_TRUST": "all",
    }
    subprocess.run(["git", "init", "--quiet"], cwd=project, check=True)
    subprocess.run([sys.executable, "src/build_chart.py"], cwd=project, env=env, check=True)
    chartbook = Path(sys.executable).with_name("chartbook.exe" if os.name == "nt" else "chartbook")
    subprocess.run([str(chartbook), "docs", "build"], cwd=project, env=env, check=True)
    return project / "docs"


def photograph(chrome: str, site: Path, scratch: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, page, (width, height), cut in SHOTS:
        for mode in ("light", "dark"):
            raw = scratch / f"{name}-{mode}.png"
            command = [
                chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--virtual-time-budget=4000",
                f"--window-size={width},{height + cut}", f"--screenshot={raw}",
                *(["--force-dark-mode"] if mode == "dark" else []),
                (site / page).as_uri(),
            ]
            subprocess.run(command, check=True, capture_output=True)
            with Image.open(raw) as image:
                image.crop((0, cut, width, height + cut)).save(OUT / f"{name}-{mode}.png", optimize=True)
            print(OUT / f"{name}-{mode}.png")


def main() -> None:
    chrome = browser()
    # A short folder: a site's deepest page is far below it, and Windows may keep paths to 260
    with tempfile.TemporaryDirectory(prefix="cbshots-") as scratch:
        root = Path(scratch)
        photograph(chrome, build(root), root)


if __name__ == "__main__":
    main()
