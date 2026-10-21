# Charts 📈

Every chart of every pipeline in this catalog, by pipeline and then by name. Search finds a chart by any word on its page.

{% if charts %}{% for page in charts %}- [{{ page.title }}]({{ page.link }}) · `{{ page.pipeline }}`{% if page.description %}: {{ page.description }}{% endif %}
{% endfor %}{% else %}No charts are declared.
{% endif %}
