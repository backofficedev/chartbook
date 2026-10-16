# Chart List

{% if charts %}{% for page in charts %}- [{{ page.title }}]({{ page.link }}){% if page.description %}: {{ page.description }}{% endif %}
{% endfor %}{% else %}No charts are declared.
{% endif %}
