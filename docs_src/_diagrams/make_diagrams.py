"""The documentation's diagrams, drawn as SVG: one light and one dark file each.

Run from the repository root: ``python docs_src/_diagrams/make_diagrams.py``. The SVGs under
``docs_src/_static/diagrams/`` are what the pages show (``only-light`` / ``only-dark``); this
script is how they are changed. Nothing imports it.

Every diagram is drawn from the same few pieces (a card, a chip, an arrow, a group), so that they
read as one set: rounded cards with a soft shadow, a chip naming what kind of thing each is, and
arrows labelled with the command that makes the step.
"""
from pathlib import Path

OUT = Path("docs_src/_static/diagrams")
PALETTES = {
    "light": dict(
        bg="none", card="#ffffff", edge="#d5dce6", shadow="#0f172a", shadow_opacity="0.10",
        text="#0f172a", muted="#526077", accent="#1f6feb", accent_soft="#e8f0fe",
        arrow="#1f6feb", group="#94a3b8", warn="#c2410c", warn_soft="#fff1e6",
        chips={"pipeline": ("#e8f0fe", "#1f4fb3"), "store": ("#ecfdf3", "#067647"),
               "reader": ("#f4ebff", "#6941c6"), "asset": ("#fef6e7", "#93370d"),
               "source": ("#f2f4f7", "#344054"), "doc": ("#e8f0fe", "#1f4fb3")},
    ),
    "dark": dict(
        bg="none", card="#161b22", edge="#30363d", shadow="#000000", shadow_opacity="0.45",
        text="#e6edf3", muted="#9aa7b4", accent="#58a6ff", accent_soft="#1c2a3d",
        arrow="#58a6ff", group="#6e7681", warn="#f0883e", warn_soft="#2d1d10",
        chips={"pipeline": ("#1c2a3d", "#79b8ff"), "store": ("#12261e", "#56d364"),
               "reader": ("#271f3d", "#bc8cff"), "asset": ("#2d2213", "#e3b341"),
               "source": ("#21262d", "#c9d1d9"), "doc": ("#1c2a3d", "#79b8ff")},
    ),
}
FONT = "font-family='Inter, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif'"
MONO = "font-family='JetBrains Mono, SFMono-Regular, Menlo, Consolas, monospace'"


def head(w, h, p):
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {w} {h}' width='{w}' height='{h}' {FONT} font-size='14'>\n"
        "<defs>"
        f"<marker id='a' viewBox='0 0 10 10' refX='8.5' refY='5' markerWidth='7' markerHeight='7' orient='auto-start-reverse'>"
        f"<path d='M 0 0 L 10 5 L 0 10 z' fill='{p['arrow']}'/></marker>"
        f"<marker id='w' viewBox='0 0 10 10' refX='8.5' refY='5' markerWidth='7' markerHeight='7' orient='auto-start-reverse'>"
        f"<path d='M 0 0 L 10 5 L 0 10 z' fill='{p['warn']}'/></marker>"
        f"<filter id='s' x='-10%' y='-10%' width='120%' height='140%'>"
        f"<feDropShadow dx='0' dy='2' stdDeviation='3' flood-color='{p['shadow']}' flood-opacity='{p['shadow_opacity']}'/></filter>"
        "</defs>\n"
    )


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, p, fill="text", size=13, weight=None, mono=False, italic=False, anchor="middle"):
    attrs = f"x='{x}' y='{y}' text-anchor='{anchor}' fill='{p[fill]}' font-size='{size}'"
    if weight:
        attrs += f" font-weight='{weight}'"
    if italic:
        attrs += " font-style='italic'"
    if mono:
        attrs += f" {MONO}"
    return f"<text {attrs}>{esc(s)}</text>\n"


def chip(cx, y, label, kind, p):
    """A small rounded label, centred on *cx*, naming what kind of thing a card is."""
    fill, ink = p["chips"][kind]
    w = 7.2 * len(label) + 18
    return (f"<rect x='{cx - w / 2}' y='{y}' width='{w}' height='20' rx='10' fill='{fill}'/>\n"
            f"<text x='{cx}' y='{y + 14}' text-anchor='middle' fill='{ink}' font-size='11' font-weight='600' letter-spacing='0.04em'>{esc(label.upper())}</text>\n")


def card_height(mono=None, sub=()):
    """How tall a card is that holds a line of code and these lines of text."""
    return 54 + (21 if mono else 0) + 19 * len(sub) + 20


def card(x, y, w, h, p, title, kind, label=None, mono=None, sub=()):
    """A card: its kind's chip, a title, a line of code under it, and lines of plain text."""
    h = max(h, card_height(mono, sub))
    s = f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='12' fill='{p['card']}' stroke='{p['edge']}' filter='url(#s)'/>\n"
    s += chip(x + w / 2, y + 12, label or kind, kind, p)
    cy = y + 54
    s += text(x + w / 2, cy, title, p, size=15.5, weight=650, mono=title.count(":") > 0 or "/" in title)
    if mono:
        cy += 21
        s += text(x + w / 2, cy, mono, p, fill="accent", mono=True, size=12)
    for line in sub:
        cy += 19
        s += text(x + w / 2, cy, line, p, fill="muted", size=12.5)
    return s


def pill(cx, cy, label, p, warn=False):
    """A command on an arrow, in code, on a soft pill."""
    w = 7.4 * len(label) + 16
    fill, ink = (p["warn_soft"], p["warn"]) if warn else (p["accent_soft"], p["accent"])
    return (f"<rect x='{cx - w / 2}' y='{cy - 11}' width='{w}' height='22' rx='11' fill='{fill}'/>\n"
            f"<text x='{cx}' y='{cy + 4}' text-anchor='middle' fill='{ink}' font-size='12' {MONO}>{esc(label)}</text>\n")


def arrow(x1, y1, x2, y2, p, label=None, at=0.5, dy=0, warn=False, dashed=False, curve=None):
    """An arrow from (x1, y1) to (x2, y2), straight or bent through *curve*, with a command on it."""
    colour = p["warn"] if warn else p["arrow"]
    marker = "w" if warn else "a"
    dash = " stroke-dasharray='6 5'" if dashed else ""
    if curve:
        cx, cy = curve
        s = f"<path d='M {x1} {y1} Q {cx} {cy} {x2} {y2}' fill='none' stroke='{colour}' stroke-width='1.6'{dash} marker-end='url(#{marker})'/>\n"
        mx, my = 0.25 * x1 + 0.5 * cx + 0.25 * x2, 0.25 * y1 + 0.5 * cy + 0.25 * y2
    else:
        s = f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' stroke='{colour}' stroke-width='1.6'{dash} marker-end='url(#{marker})'/>\n"
        mx, my = x1 + (x2 - x1) * at, y1 + (y2 - y1) * at
    if label:
        s += pill(mx, my + dy, label, p, warn=warn)
    return s


def group(x, y, w, h, p, label):
    """A dashed outline around the cards of one pipeline, named at its top left."""
    return (f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='16' fill='none' stroke='{p['group']}' stroke-width='1.2' stroke-dasharray='5 5'/>\n"
            + text(x + 14, y - 8, label, p, fill="muted", size=12, mono=True, anchor="start"))


def caption(w, y, parts, p):
    """One line under a diagram, with code in it: parts alternate plain text and code."""
    spans = "".join(
        f"<tspan {MONO} fill='{p['accent']}'>{esc(part)}</tspan>" if i % 2 else esc(part) for i, part in enumerate(parts)
    )
    return f"<text x='{w / 2}' y='{y}' text-anchor='middle' fill='{p['muted']}' font-size='13'>{spans}</text>\n"


# --- The diagrams --------------------------------------------------------------------------


def ecosystem(p):
    """The home page's: pipelines in any language publish snapshots to a store, which three readers read."""
    w, h = 940, 420
    s = head(w, h, p)
    bw, bh = 210, 96
    ys = [20, 150, 280]
    for y, (name, language, line) in zip(ys, [
        ("yield_curve", "Python", "pulls the Fed's curve"),
        ("inflation_panel", "R", "cleans a CPI panel"),
        ("event_study", "Stata", "runs the regressions"),
    ]):
        s += card(20, y, bw, bh, p, name, "pipeline", label=f"pipeline · {language}", sub=[line])
    sx, sw = 360, 220
    s += card(sx, 20, sw, 356, p, "the store", "store", mono="a folder, a drive or S3",
              sub=["", "every snapshot of every", "pipeline: what it made", "at a commit, by hash", "",
                   "yield_curve @ 4f2a91c", "inflation_panel @ 9be07d1", "event_study @ 2c41e88"])
    for y in ys:
        s += arrow(20 + bw + 4, y + bh / 2, sx - 6, y + bh / 2, p, "snapshot", at=0.5)
    rx = 710
    for y, (title, label, line1, line2) in zip(ys, [
        ("catalog site", "reader · your team", "one searchable site over", "every pipeline and version"),
        ("your agents", "reader · agents", "ls --json, get-docs,", "llms.txt, lineage"),
        ("your pipeline", "reader · a dependent", "chartbook.lock pins the", "exact snapshot it reads"),
    ]):
        s += card(rx, y, bw, bh, p, title, "reader", label=label, sub=[line1, line2])
    for y, command in zip(ys, ["catalog build", "chartbook ls", "chartbook add"]):
        s += arrow(sx + sw + 6, y + bh / 2, rx - 4, y + bh / 2, p, command)
    s += caption(w, h - 14, ["Build in any language. Publish with ", "chartbook snapshot",
                             ". Read the same, pinned facts from the browser, the command line or code."], p)
    return s + "</svg>\n"


def provenance(p):
    """Follow a number to its source: a series, a dataframe at a hash, a chart beside it and a model in another pipeline."""
    w, h = 940, 330
    s = head(w, h, p)
    bw, bh = 200, 104
    s += card(20, 110, 170, bh, p, "Fed yield curve", "source", label="source", mono="feds200628.csv", sub=["the Board's fitted curve"])
    s += group(240, 28, 470, 246, p, "yield_curve")
    s += card(262, 110, bw, bh, p, "fed_yield_curve", "asset", label="dataframe", mono="sha256:1b8e…", sub=["17,053 rows, 31 columns"])
    s += card(492, 48, bw, bh - 8, p, "chart/treasury_yields", "asset", label="chart", sub=["made from 1b8e…"])
    s += group(740, 166, 186, 132, p, "rate_forecast")
    s += card(752, 180, 162, bh, p, "model/forecast", "asset", label="model", sub=["trained on 1b8e…", "pinned in chartbook.lock"])
    s += arrow(194, 162, 258, 162, p, "pull")
    s += arrow(466, 150, 488, 104, p)
    s += arrow(466, 178, 748, 230, p, "pin", at=0.62, curve=(600, 240))
    s += caption(w, h - 4, ["", "chartbook lineage", " walks every number back to its source, through every pin, and checks each hash on the way."], p)
    return s + "</svg>\n"


def chain(p):
    """How the build works: repository, index, pages, site."""
    w, h = 920, 210
    s = head(w, h, p)
    xs, bw, bh, y = [20, 260, 500, 740], 160, 0, 20
    items = [
        ("repository", "doc", "a folder in git", ["manifest, code,", "write-ups, data"]),
        ("index", "doc", "index.json", ["the facts: IDs, hashes,", "inputs, pins"]),
        ("pages", "doc", "Markdown", ["text for one site tool,", "written from the index"]),
        ("site", "reader", "HTML", ["built by the site tool:", "Sphinx or MkDocs"]),
    ]
    for x, (title, kind, mono, sub) in zip(xs, items):
        s += card(x, y, bw, bh, p, title, kind, label="step" if kind == "doc" else "result", mono=mono, sub=sub)
    bh = card_height("x", ("x", "x"))
    for (x1, x2), label in zip(zip(xs[:-1], xs[1:]), ("resolve", "write", "build")):
        s += arrow(x1 + bw + 4, y + bh / 2, x2 - 6, y + bh / 2, p, label)
    s += caption(w, h - 20, ["One command, ", "chartbook docs build",
                             ", does all three. When anything disagrees with the repository, the repository is right."], p)
    return s + "</svg>\n"


def documents(p):
    """The four documents: what each records, who writes it, where it lives."""
    w, h = 900, 310
    s = head(w, h, p)
    xs, bw, y = [20, 245, 470, 695], 185, 16
    bh = card_height("x", ("x", "x", "x"))
    items = [
        ("manifest", "chartbook.toml", ["asks: which assets,", "where, and what it", "depends on"], ("people",), "in git"),
        ("lockfile", "chartbook.lock", ["records what was got:", "the snapshot each", "dependency is pinned to"], ("chartbook pin, update",), "in git, no timestamp"),
        ("snapshot", "_chartbook/snapshot.json", ["records what was made:", "every asset built at", "one commit, by hash"], ("chartbook snapshot",), "in the store, not git"),
        ("index", "index.json", ["records what a site", "shows: every record,", "pins reported"], ("chartbook docs build",), "beside the site"),
    ]
    for x, (title, mono, sub, by, where) in zip(xs, items):
        s += card(x, y, bw, bh, p, title, "doc", label="document", mono=mono, sub=sub)
        cx = x + bw / 2
        s += text(cx, y + bh + 26, "written by", p, fill="muted", size=11.5)
        for i, line in enumerate(by):
            s += pill(cx, y + bh + 46 + 24 * i, line, p)
        s += text(cx, y + bh + 84, where, p, fill="muted", size=12.5)
    s += caption(w, h - 12, ["A manifest asks, a lockfile records what was got, a snapshot records what was made, and an index records what a site shows."], p)
    return s + "</svg>\n"


def depending(p):
    """Depending on another pipeline: their folder, a snapshot in the store, your folder."""
    w, h = 900, 280
    s = head(w, h, p)
    bw, y = 200, 30
    bh = card_height("x", ("x", "x"))
    s += card(20, y, bw, bh, p, "fed_yield_curve", "pipeline", label="their folder", sub=["they build it;", "it may be mid-change"])
    s += card(350, y, bw, bh, p, "snapshot", "store", label="in the store", mono="4f2a91c · sha256 each",
              sub=["what they built at that", "commit, declared ready"])
    s += card(680, y, bw, bh, p, "rate_forecast", "pipeline", label="your folder", sub=["chartbook.lock pins it;", "data.load() reads the copy"])
    s += arrow(20 + bw + 4, y + bh / 2, 350 - 6, y + bh / 2, p, "run --snapshot")
    s += arrow(350 + bw + 4, y + bh / 2, 680 - 6, y + bh / 2, p, "chartbook pin")
    s += arrow(120, y + bh + 6, 780, y + bh + 6, p, "never: one pipeline reads another's folder", warn=True, dashed=True, curve=(450, 262))
    s += caption(w, h - 12, ["A newer snapshot moves nothing until you run ", "chartbook update",
                             "; a ", "git diff", " of the lockfile shows the move."], p)
    return s + "</svg>\n"


DIAGRAMS = {
    "ecosystem": ecosystem,
    "provenance": provenance,
    "chain": chain,
    "documents": documents,
    "depending": depending,
}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, draw in DIAGRAMS.items():
        for mode, palette in PALETTES.items():
            (OUT / f"{name}-{mode}.svg").write_text(draw(palette), encoding="utf-8", newline="\n")
            print(OUT / f"{name}-{mode}.svg")
