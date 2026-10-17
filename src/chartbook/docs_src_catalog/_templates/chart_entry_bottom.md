## Chart Specs

| Chart Name             | {{name}}                                                   |
|------------------------|------------------------------------------------------------|
| Chart ID               | {{chart_id}}                                               |
{% if tags %}| Tags                   | {{tags | join(', ')}}                                      |
{% endif %}{% if start_date %}| Data Series Start Date | {{start_date}}                                             |
{% endif %}{% if frequency %}| Data Frequency         | {{frequency}}                                              |
{% endif %}{% if observation_period %}| Observation Period     | {{observation_period}}                                     |
{% endif %}{% if release_lag %}| Lag in Data Release    | {{release_lag}}                                            |
{% endif %}{% if release_timing %}| Data Release Timing    | {{release_timing}}                                         |
{% endif %}{% if seasonal_adjustment %}| Seasonal Adjustment    | {{seasonal_adjustment}}                                    |
{% endif %}{% if units %}| Units                  | {{units}}                                                  |
{% endif %}{% if series %}| Data Series            | {{series | join(', ')}}                                            |
{% endif %}| HTML Chart             | [HTML](../download_chart/{{pipeline_id | replace('/', '--')}}/{{chart_id}}.html)    |
{% if excel_chart_exists %}| Excel Chart             | [Excel]({{excel_chart_download_path}})    |{% endif %}

## Dataframe Manifest

{% include "dataframe_manifest.md" %}

## Pipeline Manifest

{% include "pipeline_manifest.md" %}
