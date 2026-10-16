# Versions 🕰️

Every pipeline of this catalog, in two kinds of version. The **working version** is the
pipeline's folder as it is now, which the rest of this site shows. A **snapshot** is a version
its owner declared ready (`chartbook snapshot`); a pipeline that depends on another reads the
snapshot it pinned, never the folder. Each snapshot's site is built from the store alone, as the
pipeline's own site, with the write-ups and the data dictionary as they were then.

{% for p in pipelines %}
## {{ p.name }}

`{{ p.id }}` · {% if p.working %}[the working version]({{ p.readme }}){% else %}not on this machine: [its page]({{ p.readme }}){% endif %}

{% if p.versions %}
<ul class="cb-versions">
{% for v in p.versions %}<li><a href="{{ v.link }}"><code>{{ v.short }}</code>, made {{ v.made }}</a>{% if v.built_by_run %} · built by <code>chartbook run</code>{% endif %}{% if v.pinned_by %} · pinned by {% for o in v.pinned_by %}<code>{{ o }}</code>{% if not loop.last %}, {% endif %}{% endfor %}{% endif %}</li>
{% endfor %}</ul>
{% else %}
No snapshot of it is in the store.
{% endif %}
{% endfor %}
