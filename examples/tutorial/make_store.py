"""Build the tutorial's store: the three pipelines here, built and snapshotted, exported to a zip.

The zip is what the tutorial downloads (docs_src/tutorials/explore-a-catalog.md), attached to each
ChartBook release as ``chartbook-tutorial-store.zip``. It is made in two steps, because
``rate_outlook`` pins the other two, and a snapshot needs its pins committed:

    python examples/tutorial/make_store.py upstream --store C:/tutstore
    git commit examples/tutorial/rate_outlook/chartbook.lock -m "Pin the tutorial store's snapshots"
    python examples/tutorial/make_store.py downstream --store C:/tutstore --zip chartbook-tutorial-store.zip

Run each in a clean checkout, with the ChartBook of the release (``uv run python ...``): a snapshot
records the commit it was made at, so everything in the pipelines' folders is committed. The store
is a folder of its own, new or made by the first step; nothing under ``~/.chartbook`` is read or
written. Pulls need the network: the Federal Reserve Board's site, and FRED.

Every series in it is a work of the U.S. government, in the public domain: the Board's
zero-coupon yield curve; BLS's unemployment rate, CPI and payrolls; BEA's real GDP.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
UPSTREAM = ["treasury_curve", "macro_basics"]
DOWNSTREAM = "rate_outlook"
PIPELINES = {name: f"tutorial/{name}" for name in [*UPSTREAM, DOWNSTREAM]}


def chartbook(*arguments, cwd, store):
    """Run this interpreter's chartbook in *cwd*, with the store and nothing else of this machine's."""
    command = Path(sys.executable).with_name("chartbook.exe" if os.name == "nt" else "chartbook")
    scratch = Path(store).parent / f".{Path(store).name}-home"
    env = {
        **os.environ,
        "CHARTBOOK_STORE": str(store),
        "CHARTBOOK_CACHE": str(scratch / "cache"),
        "CHARTBOOK_GIT_CACHE": str(scratch / "git"),
        "CHARTBOOK_SYSTEM_SETTINGS": str(scratch / "system-settings.toml"),
        # These folders are this checkout's own, built as their owner would
        "CHARTBOOK_TRUST": "all",
    }
    print(f"$ chartbook {' '.join(arguments)}   ({cwd.name})", flush=True)
    subprocess.run([str(command), *arguments], cwd=cwd, env=env, check=True)


def upstream(store):
    for name in UPSTREAM:
        chartbook("run", "--snapshot", cwd=HERE / name, store=store)
    folder = HERE / DOWNSTREAM
    lockfile = folder / "chartbook.lock"
    chartbook("update" if lockfile.exists() else "pin", cwd=folder, store=store)
    changed = subprocess.run(["git", "status", "--porcelain", "--", str(lockfile)], cwd=HERE, capture_output=True, text=True, check=True).stdout
    if changed.strip():
        print(f"\n{lockfile.relative_to(HERE.parent.parent)} moved: commit it, then run `downstream`.")
    else:
        print("\nThe pins did not move: run `downstream`.")


def downstream(store, zip_path):
    chartbook("run", "--snapshot", cwd=HERE / DOWNSTREAM, store=store)
    with tempfile.TemporaryDirectory(prefix="cbtut-") as scratch:
        staged = Path(scratch) / "chartbook-tutorial-store"
        for pipeline in PIPELINES.values():
            chartbook("store", "export", pipeline, "--latest", "--to", str(staged), cwd=HERE, store=store)
        archive = shutil.make_archive(str(Path(zip_path).with_suffix("")), "zip", root_dir=scratch, base_dir=staged.name)
    print(f"\nWrote {archive}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("step", choices=["upstream", "downstream"])
    parser.add_argument("--store", required=True, help="The folder of the tutorial's store")
    parser.add_argument("--zip", default="chartbook-tutorial-store.zip", help="Where `downstream` writes the zip")
    arguments = parser.parse_args()
    store = Path(arguments.store).resolve()
    if arguments.step == "upstream":
        upstream(store)
    else:
        downstream(store, Path(arguments.zip).resolve())


if __name__ == "__main__":
    main()
