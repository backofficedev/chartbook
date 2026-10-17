{% if dependencies %}
## Dependencies

The pipelines this one reads from, as its `[dependencies]` declares them, and what `chartbook.lock` pins each to.

{% for dependency in dependencies %}
- {% if dependency.html_link %}<a href="{{dependency.html_link}}">{{dependency.label}}</a>{% elif dependency.link %}[{{dependency.label}}]({{dependency.link}}){% else %}{{dependency.label}}{% endif %} ({{dependency.declared}}): {{dependency.pinned}}
{% endfor %}
{% endif %}
