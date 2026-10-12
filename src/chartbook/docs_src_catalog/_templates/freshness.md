{% if freshness %}
```{raw} html
<p class="cb-freshness">{% for fact in freshness %}{{fact.label}} <time class="cb-relative-time" datetime="{{fact.iso}}" title="{{fact.title}}">{{fact.date}}</time>{% if not loop.last %} · {% endif %}{% endfor %}</p>
```
{% endif %}
