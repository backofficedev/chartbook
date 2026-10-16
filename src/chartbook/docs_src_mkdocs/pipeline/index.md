# {{pipeline_manifest.project.name}}

{% include "freshness.md" %}

Last updated: {{ today }}

{% if site_pages %}
## Site Pages

{% for page in site_pages %}- [{{ page.title }}]({{ page.link }})
{% endfor %}
{% endif %}
{% if notebooks %}
## Notebooks 📖

{% for page in notebooks %}- [{{ page.title }}]({{ page.link }})
{% endfor %}
{% endif %}
{% if notes %}
## Notes 📝

{% for page in notes %}- [{{ page.title }}]({{ page.link }})
{% endfor %}
{% endif %}
## Pipeline Charts 📈

{% if charts %}{% for page in charts %}- [{{ page.title }}]({{ page.link }})
{% endfor %}{% else %}No charts are declared.
{% endif %}
{% if dataframes %}
## Dataframes 📊

{% for page in dataframes %}- [{{ page.title }}]({{ page.link }})
{% endfor %}
{% endif %}
{% if models %}
## Models 🤖

{% for page in models %}- [{{ page.title }}]({{ page.link }})
{% endfor %}
{% endif %}

{{ readme_text }}

## Pipeline Specs

{% include "pipeline_manifest.md" %}
