"""The documentation's diagrams, drawn as SVG: one light and one dark file each.

Run from the repository root: ``python docs_src/_diagrams/make_diagrams.py``. The SVGs under
``docs_src/_static/diagrams/`` are what the pages show (``only-light`` / ``only-dark``); this
script is how they are changed. Nothing imports it.
"""
from pathlib import Path

OUT = Path("docs_src/_static/diagrams")
PALETTES = {
    "light": dict(box="#f4f7fb", stroke="#2b4c7e", text="#1f2937", muted="#4b5563", accent="#2b6cb0", arrow="#2b4c7e", warn="#b45309"),
    "dark": dict(box="#1f2937", stroke="#93c5fd", text="#e5e7eb", muted="#9ca3af", accent="#60a5fa", arrow="#93c5fd", warn="#fbbf24"),
}
FONT = "font-family='-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif'"
MONO = "font-family='SFMono-Regular, Menlo, Consolas, monospace'"


def head(w, h, p):
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {w} {h}' width='{w}' height='{h}' {FONT} font-size='14'>\n"
        f"<defs><marker id='a' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='8' markerHeight='8' orient='auto-start-reverse'>"
        f"<path d='M 0 0 L 10 5 L 0 10 z' fill='{p['arrow']}'/></marker></defs>\n"
    )


def text(x, y, s, p, fill="text", size=12.5, weight=None, mono=False, italic=False, anchor="middle"):
    attrs = f"x='{x}' y='{y}' text-anchor='{anchor}' fill='{p[fill]}' font-size='{size}'"
    if weight:
        attrs += f" font-weight='{weight}'"
    if italic:
        attrs += " font-style='italic'"
    if mono:
        attrs += f" {MONO}"
    return f"<text {attrs}>{s}</text>\n"


def box(x, y, w, h, p, title, sub=(), mono=None):
    s = f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='8' fill='{p['box']}' stroke='{p['stroke']}' stroke-width='1.5'/>\n"
    cy = y + 26
    s += text(x + w / 2, cy, title, p, size=15, weight=600)
    if mono:
        cy += 20
        s += text(x + w / 2, cy, mono, p, fill="accent", mono=True)
    for line in sub:
        cy += 18
        s += text(x + w / 2, cy, line, p, fill="muted")
    return s


def arrow(x1, y1, x2, y2, p, labels=(), above=True):
    s = f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' stroke='{p['arrow']}' stroke-width='1.5' marker-end='url(#a)'/>\n"
    ly = (y1 + y2) / 2 + (-8 - 15 * (len(labels) - 1) if above else 18)
    for label in labels:
        s += text((x1 + x2) / 2, ly, label, p, fill="muted", italic=True)
        ly += 15
    return s


def chain(p):
    w, h = 820, 190
    s = head(w, h, p)
    xs, bw, bh, y = [20, 230, 440, 650], 150, 92, 40
    items = [
        ("repository", "a folder in git", ["manifest, code,", "write-ups, data"]),
        ("index", "index.json", ["the facts: IDs, hashes,", "inputs, pins"]),
        ("pages", "Markdown", ["text for one site tool,", "written from the index"]),
        ("site", "HTML", ["built by the site tool,", "Sphinx today"]),
    ]
    for x, (t, m, sub) in zip(xs, items):
        s += box(x, y, bw, bh, p, t, sub=sub, mono=m)
    for (x1, x2), label in zip(zip(xs[:-1], xs[1:]), ("resolve", "write", "build")):
        s += arrow(x1 + bw + 4, y + bh / 2, x2 - 4, y + bh / 2, p, [label])
    s += (f"<text x='{w / 2}' y='{h - 20}' text-anchor='middle' fill='{p['muted']}' font-size='13'>one command, "
          f"<tspan {MONO} fill='{p['accent']}'>chartbook docs</tspan>, does all three; when anything disagrees with the repository, the repository is right</text>\n")
    return s + "</svg>\n"


def documents(p):
    w, h = 820, 250
    s = head(w, h, p)
    xs, bw, bh, y = [20, 220, 420, 620], 180, 122, 24
    items = [
        ("manifest", "chartbook.toml", ["asks:", "which assets, where,", "what it depends on"], ("people",), "in git"),
        ("lockfile", "chartbook.lock", ["records what was got:", "which snapshot each", "dependency is pinned to"], ("chartbook pin, update", "(run, for a first pin)"), "in git, no timestamp"),
        ("snapshot", "store/snapshots/…", ["records what was made:", "every asset built at one", "commit, with its hash"], ("chartbook snapshot", "or run --snapshot"), "in the store, not in git"),
        ("index", "index.json", ["records what a site shows:", "every record of every", "pipeline, pins reported"], ("chartbook docs, build",), "beside the site"),
    ]
    for x, (t, m, sub, by, where) in zip(xs, items):
        s += box(x, y, bw, bh, p, t, sub=sub, mono=m)
        cx = x + bw / 2
        s += text(cx, y + bh + 22, "written by", p, fill="muted", size=11.5)
        cy = y + bh + 40
        for line in by:
            s += text(cx, cy, line, p, fill="accent", mono=True, size=12.5)
            cy += 17
        s += text(cx, y + bh + 94, where, p, fill="muted")
    return s + "</svg>\n"


def depending(p):
    w, h = 820, 300
    s = head(w, h, p)
    bw, bh, y = 200, 110, 40
    s += box(20, y, bw, bh, p, "fed_yield_curve", mono="their folder", sub=["they build it;", "it may be mid-change"])
    s += box(310, y, bw, bh, p, "snapshot", mono="snapshots/4f2a91c…/…", sub=["what they built at that", "commit, declared ready"])
    s += box(600, y, bw, bh, p, "rate_forecast", mono="your folder", sub=["chartbook.lock pins it;", "data.load() reads the copy"])
    s += arrow(224, y + bh / 2, 306, y + bh / 2, p, ["chartbook run", "--snapshot"], above=False)
    s += arrow(514, y + bh / 2, 596, y + bh / 2, p, ["chartbook pin"], above=False)
    s += (f"<path d='M 120 {y + bh + 4} C 120 232, 700 232, 700 {y + bh + 4}' fill='none' stroke='{p['warn']}' "
          f"stroke-width='1.5' stroke-dasharray='6 4' marker-end='url(#a)'/>\n")
    s += text(410, 252, "never: a pipeline does not read another's folder", p, fill="warn", italic=True)
    s += (f"<text x='{w / 2}' y='{h - 22}' text-anchor='middle' fill='{p['muted']}' font-size='13'>a newer snapshot moves nothing until you say "
          f"<tspan {MONO} fill='{p['accent']}'>chartbook update</tspan>; a <tspan {MONO} fill='{p['accent']}'>git diff</tspan> of the lockfile shows the move</text>\n")
    return s + "</svg>\n"


for name, draw in (("chain", chain), ("documents", documents), ("depending", depending)):
    for mode, palette in PALETTES.items():
        (OUT / f"{name}-{mode}.svg").write_text(draw(palette))
print("written")
