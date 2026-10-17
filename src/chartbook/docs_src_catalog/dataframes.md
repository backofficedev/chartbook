# Dataframes 📊

```{toctree}
:maxdepth: 1
{% for file_path in dataframe_file_list %}
{{file_path}}
{% endfor %}
```
{% if stored_dataframes %}

## Not on this machine

The dataframes of the pipelines this catalog shows from the store, as the newest snapshot of each
lists them, each linked to its page in that snapshot's site.

{% for entry in stored_dataframes %}{% if entry.more %}- and {{ entry.more }} more of `{{ entry.pipeline }}`, in <a href="{{ entry.link }}">its snapshot's site</a>{% else %}- <a href="{{ entry.link }}">{{ entry.title }}</a> · `{{ entry.pipeline }}`{% endif %}
{% endfor %}{% endif %}
