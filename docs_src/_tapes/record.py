"""The documentation's terminal recordings, made with VHS in Docker: one MP4 and one WebM each.

Run from the repository root, with Docker running:

    python docs_src/_tapes/record.py --store-zip chartbook-tutorial-store.zip

Each ``*.tape`` here is a script of what is typed and when; ``_settings.tape`` is what they share.
They are recorded in an image of VHS with Python and this checkout's ChartBook (built into a
wheel here, so the recordings show the ChartBook of the checkout; ``--wheel`` gives another), and written to
``docs_src/_static/tapes/``, which the pages embed. Each runs in a container of its own, from
nothing: the Quickstart's files (``docs_src/_examples/quickstart/``) and the tutorial's store
(the zip ``examples/tutorial/make_store.py`` writes) are all it is given. Nothing imports this.
"""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "docs_src" / "_static" / "tapes"
IMAGE = "chartbook-vhs"


def build_image(wheel=None) -> None:
    with tempfile.TemporaryDirectory(prefix="cbtapes-") as context:
        if wheel:
            shutil.copy(wheel, context)
        else:
            subprocess.run(["uv", "build", "--wheel", "-o", context], cwd=ROOT, check=True)
        shutil.copy(HERE / "Dockerfile", context)
        subprocess.run(["docker", "build", "-q", "-t", IMAGE, context], check=True)


def record(tape: Path, store_zip: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    mounts = {
        HERE: "/tapes",
        ROOT / "docs_src" / "_examples" / "quickstart": "/src",
        store_zip.parent: "/zip",
        OUT: "/out",
    }
    volumes = [arg for host, guest in mounts.items() for arg in ("-v", f"{host}:{guest}")]
    print(f"recording {tape.name}", flush=True)
    subprocess.run(["docker", "run", "--rm", *volumes, IMAGE, f"/tapes/{tape.name}"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--store-zip", type=Path, required=True, help="The tutorial's store, chartbook-tutorial-store.zip")
    parser.add_argument("--wheel", type=Path, help="Record with this wheel of ChartBook, not one built from the checkout")
    parser.add_argument("tapes", nargs="*", help="The tapes to record, by name (all if none)")
    arguments = parser.parse_args()
    store_zip = arguments.store_zip.resolve()
    if store_zip.name != "chartbook-tutorial-store.zip":
        parser.error("the tapes look for chartbook-tutorial-store.zip: name the zip so")
    build_image(arguments.wheel)
    tapes = [HERE / f"{name.removesuffix('.tape')}.tape" for name in arguments.tapes] or sorted(
        tape for tape in HERE.glob("*.tape") if not tape.name.startswith("_")
    )
    for tape in tapes:
        record(tape, store_zip)


if __name__ == "__main__":
    main()
