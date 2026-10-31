{% if provenance %}
## Provenance

{% if provenance.links %}
**This build reads working copies; their pins are not in use.**
{% for link in provenance.links %}
- `{{link.pipeline}}` at `{{link.path}}`, commit `{{link.commit}}`{% if link.uncommitted %}, with uncommitted changes{% endif %}.
{% endfor %}
{% endif %}

What this is, where it is, what made it and from what, as `index.json` records it.

| | |
|--------------------------------|--------------------------------------------------------------------------------------|
| What                           | {{provenance.kind}} `{{provenance.id}}`, of pipeline `{{provenance.pipeline}}`     |
| Where                          | {{provenance.where}}                                                                 |
| Content                        | {{provenance.content}}                                                               |
{% if provenance.build %}| Built by                       | `{{provenance.build}}` in `{{provenance.pipeline}}`                                 |
{% endif %}{% if provenance.version %}| Version                        | `{{provenance.version.name}}`{% if provenance.version.labels %} ({{provenance.version.labels | join(', ')}}){% endif %}, made {{provenance.version.made_at[:10]}} at commit `{{provenance.version.commit[:7]}}` |
{% endif %}{% if provenance.series %}| Series                         | {{provenance.series}} columns documented                                             |
{% endif %}
{% if provenance.inputs %}
**Made from:**
{% for input in provenance.inputs %}
- {% if input.link %}<a href="{{input.link}}">`{{input.id}}`</a>{% else %}`{{input.id}}`{% endif %}: {{input.words}}
{% endfor %}
{% endif %}
{% if provenance.used_by %}
**Used by:** {% for other in provenance.used_by %}`{{other}}`{% if not loop.last %}, {% endif %}{% endfor %}
{% endif %}
{% endif %}
