"""The documentation's logo, light and dark, and its social card.

Run from the repository root: ``python docs_src/_diagrams/make_brand.py``. It writes, under
``docs_src/_static/``:

- ``logo-light.png`` and ``logo-dark.png``: ``logo.png`` cut to its edges, its background made
  transparent; in the dark one the black of "Book" is near-white and the navy of "Chart" lighter,
  so that both read on the dark theme;
- ``social-card.png``: the 1200x630 picture a link to the docs shows on Slack, X or LinkedIn,
  drawn by a headless Chrome or Edge from HTML (``CHROME`` names it, as for the screenshots).

Nothing imports it.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

STATIC = Path("docs_src/_static")
HEADLINE = "Know exactly where every number came from."
SUB = ("ChartBook connects your team's data pipelines, in any language, so each one builds on another's exact, "
       "versioned output: traced to its sources, verified by hash, in one catalog for people and agents.")


def transparent(rgb: np.ndarray) -> np.ndarray:
    """A picture on a white ground, as RGBA with the white taken out (as GIMP's "colour to alpha")."""
    rgb = rgb.astype(float)
    alpha = (255 - rgb).max(axis=2) / 255
    safe = np.where(alpha > 0, alpha, 1)[..., None]
    colour = np.clip((rgb - 255 * (1 - alpha[..., None])) / safe, 0, 255)
    # Inside the shapes the colour is the logo's own, solid: a light blue is not half see-through
    solid = alpha > 0.5
    colour[solid] = rgb[solid]
    alpha[solid] = 1
    return np.dstack([colour, alpha * 255])


#: How wide the logos are saved: a sidebar shows them at a fifth of this
LOGO_WIDTH = 640


def save(rgba: np.ndarray, name: str) -> None:
    image = Image.fromarray(rgba.astype(np.uint8), "RGBA")
    image = image.resize((LOGO_WIDTH, round(image.height * LOGO_WIDTH / image.width)), Image.LANCZOS)
    image.save(STATIC / name, optimize=True)


def logos() -> None:
    rgba = transparent(np.asarray(Image.open(STATIC / "logo.png").convert("RGB")))
    rgba[..., 3] = np.where(rgba[..., 3] < 20, 0, rgba[..., 3])  # the paper's grain is not the logo
    ys, xs = np.nonzero(rgba[..., 3] > 40)
    pad = 40
    top, bottom = max(ys.min() - pad, 0), min(ys.max() + pad, rgba.shape[0])
    left, right = max(xs.min() - pad, 0), min(xs.max() + pad, rgba.shape[1])
    rgba = rgba[top:bottom, left:right]
    save(rgba, "logo-light.png")

    dark = rgba.copy()
    r, g, b = dark[..., 0], dark[..., 1], dark[..., 2]
    black = (np.maximum(np.maximum(r, g), b) < 90) & (np.abs(r - b) < 40)
    dark[black, :3] = [230, 237, 243]
    # The word "Chart" is the navy at the left; the binder, to its right, keeps its colour
    words = np.zeros(black.shape, bool)
    words[:, : int(dark.shape[1] * 0.65)] = True
    navy = words & (b > r + 40)
    dark[navy, :3] = dark[navy, :3] * 0.45 + np.array([150, 200, 255]) * 0.55
    save(dark, "logo-dark.png")


def browser() -> str:
    for candidate in [os.environ.get("CHROME"),
                      r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                      r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                      "google-chrome", "chromium", "chromium-browser"]:
        if candidate and (Path(candidate).is_file() or shutil.which(candidate)):
            return candidate
    sys.exit("No Chrome or Edge found: set CHROME to the browser's executable.")


def social_card() -> None:
    logo = (STATIC / "logo-dark.png").resolve().as_uri()
    page = f"""<!doctype html><html><head><meta charset="utf-8"><style>
    html, body {{ margin: 0; width: 1200px; height: 630px; overflow: hidden; }}
    body {{ background: radial-gradient(circle at 85% 20%, #1c2a3d 0, #0d1117 60%); color: #e6edf3;
            font-family: Inter, "Segoe UI", -apple-system, Helvetica, Arial, sans-serif; }}
    .card {{ position: absolute; inset: 72px 80px; display: flex; flex-direction: column; }}
    img {{ height: 80px; align-self: flex-start; }}
    .eyebrow {{ margin-top: 34px; color: #58a6ff; font-size: 22px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; }}
    h1 {{ margin: 12px 0 0; font-size: 64px; line-height: 1.05; font-weight: 800; letter-spacing: -.02em; }}
    p {{ margin: 22px 0 0; max-width: 1000px; color: #9aa7b4; font-size: 25px; line-height: 1.4; }}
    .url {{ margin-top: auto; color: #58a6ff; font-size: 22px; font-family: Consolas, Menlo, monospace; }}
    </style></head><body><div class="card"><img src="{logo}" alt="">
    <div class="eyebrow">Data pipelines with provenance</div><h1>{HEADLINE}</h1><p>{SUB}</p>
    <div class="url">backofficedev.github.io/chartbook</div></div></body></html>"""
    with tempfile.TemporaryDirectory(prefix="cbcard-") as scratch:
        html = Path(scratch) / "card.html"
        html.write_text(page, encoding="utf-8")
        subprocess.run([browser(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1200,630",
                        "--virtual-time-budget=2000", f"--screenshot={(STATIC / 'social-card.png').resolve()}", html.as_uri()],
                       check=True, capture_output=True)


if __name__ == "__main__":
    logos()
    social_card()
    for name in ("logo-light.png", "logo-dark.png", "social-card.png"):
        print(STATIC / name)
