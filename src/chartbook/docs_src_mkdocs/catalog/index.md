# {{manifest.project.name}}

Last updated: {{ today }}

- 📈 **[Charts](cb/charts.md)**: every chart of every pipeline, searchable by name, tag or source.
- 📊 **[Dataframes](cb/dataframes.md)**: the dataframes each pipeline produces, which the charts are made from.
{% if model_file_list %}- 🤖 **[Models](cb/models.md)**: the trained models the pipelines produce, what each was trained on, and how it scores.
{% endif %}{% if files_file_list %}- 🗂️ **[Files](cb/files.md)**: the files the pipelines keep as they are, whatever is inside: archives, text, PDFs, images, arrays.
{% endif %}- 🔌 **[Pipelines](cb/pipelines.md)**: the pipelines that make the dataframes and charts.
{% if has_versions %}- 🕰️ **[Versions](cb/versions.md)**: every snapshot of every pipeline in the store, each its own site as it was when its owner declared it ready, and which pipeline pins it.
{% endif %}- 👋 **[Contributing](contributing.md)**: how to contribute to this catalog.
- 🩺 **[Diagnostics](cb/diagnostics.md)**: which pipelines, dataframes and charts are missing the fields the catalog's policy asks for, with a CSV to download.

{{ readme_text }}

{% if has_stores %}- **[Stores](cb/stores.md)**: locations, routing, reachability and snapshot counts.
{% endif %}
