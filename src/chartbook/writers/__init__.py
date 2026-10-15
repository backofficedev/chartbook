"""Writers: each turns the index into pages for one site tool.

A writer reads the index and the files the index names, write-ups, data
files and chart files, at the paths the index gives, and nothing else: no
manifest, no folder walk, no git (``docs_src/design/writer.md``). The
Sphinx writer is the first; it replaces the page generator section by
section, each page compared whole with the generator's on the example
sites until the generator can go.
"""
