"""Writers: each turns the index into pages for one site tool.

A writer reads the index and the files the index names, write-ups, data
files and chart files, at the paths the index gives, and nothing else: no
manifest, no folder walk, no git (``docs_src/design/writer.md``). The
Sphinx writer came first and replaced the page generator; the MkDocs
writer is a subclass of it, with a theme folder of its own. ``[project]
writer`` in a manifest names which one builds a site, and
:func:`writer_class` finds it.
"""


#: The assistant file's name, at a site's root beside ``index.json``, after
#: the llms.txt convention (https://llmstxt.org): what is in the site and
#: where, for a command-line agent. Every writer writes one.
ASSISTANT_FILE = "llms.txt"


def writer_class(name: str):
    """The writer class for a site tool named in ``[project] writer``.

    :raises ValueError: If no writer has that name.
    """
    if name == "sphinx":
        from chartbook.writers.sphinx import SphinxWriter

        return SphinxWriter
    if name == "mkdocs":
        from chartbook.writers.mkdocs import MkDocsWriter

        return MkDocsWriter
    raise ValueError(f"No writer is named {name!r}; the writers are: sphinx, mkdocs.")
