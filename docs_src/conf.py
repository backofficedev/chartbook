# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import sys
from pathlib import Path

# Add the src directory to sys.path for autodoc2
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "chartbook"
copyright = "2025, Jeremiah Bejarano"
author = "Jeremiah Bejarano"
release = "0.0.1"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "myst_nb",
    "autodoc2",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx_design",
    "sphinx_copybutton",
    "sphinx.ext.viewcode",
    "sphinx.ext.githubpages",
]

# autodoc2 configuration
autodoc2_packages = [
    "../src/chartbook",
]

# Use MyST for docstrings
autodoc2_render_plugin = "myst"
autodoc2_hidden_objects = ["dunder", "private", "inherited"]
autodoc2_sort_names = True
autodoc2_class_doc_style = "both"  # Include both class and __init__ docstrings

# Suppress specific warnings
suppress_warnings = [
    "autodoc2.dup_item",  # Suppress duplicate item warnings (e.g., settings.defaults intentional redefinition)
]

# MyST configuration
myst_enable_extensions = [
    "amsmath",
    "colon_fence",
    "deflist",
    "dollarmath",
    "fieldlist",
    "html_admonition",
    "html_image",
    "linkify",
    "replacements",
    "smartquotes",
    "strikethrough",
    "substitution",
    "tasklist",
]

# MyST-NB configuration
nb_execution_mode = "off"
nb_execution_timeout = 300
nb_output_stderr = "show"

# Intersphinx configuration
intersphinx_mapping = {
    "python": ("https://docs.python.org/3/", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
    "plotly": ("https://plotly.com/python-api-reference/", None),
}

templates_path = ["_templates"]
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    "**.ipynb_checkpoints",
    "apidocs/index.rst",
    "apidocs/chartbook/chartbook.md",
    "apidocs/chartbook/chartbook.__about__.md",
    "apidocs/chartbook/chartbook.build_markdown.md",
    "apidocs/chartbook/chartbook.create_data_glimpses.md",
    "apidocs/chartbook/chartbook.orgvars.md",
    "apidocs/chartbook/chartbook.publish.md",
    "apidocs/chartbook/chartbook.scripts.md",
    "apidocs/chartbook/chartbook.settings.md",
    "apidocs/chartbook/chartbook.utils.md",
]

# Date format
today_fmt = "%B %d, %Y"

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_book_theme"
html_static_path = ["_static"]

html_theme_options = {
    "home_page_in_toc": True,
    "navigation_with_keys": True,
    "show_navbar_depth": 2,
    "show_toc_level": 3,
    "navbar_end": ["theme-switcher", "navbar-icon-links"],
    "icon_links": [
        {
            "name": "Repository",
            "url": "https://github.com/backofficedev/chartbook",
            "icon": "fa-solid fa-code-branch",
        },
    ],
}

html_title = "ChartBook Documentation"
html_logo = "_static/logo.png"
html_favicon = "_static/logo.png"

# Custom CSS/JS
html_css_files = [
    "custom.css",
]

# Sidebar configuration
html_sidebars = {
    "**": [
        "navbar-logo.html",
        "search-button-field.html",
        "sbt-sidebar-nav.html",
    ]
}
