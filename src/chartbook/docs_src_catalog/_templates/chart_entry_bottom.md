## Chart Specs

| Chart Name             | {{chart_name}}                                             |
|------------------------|------------------------------------------------------------|
| Chart ID               | {{chart_id}}                                               |
| Topic Tags             | {{topic_tags | join(', ')}}                                |
| Data Series Start Date | {{data_series_start_date}}                                 |
| Data Frequency         | {{data_frequency}}                                         |
| Observation Period     | {{observation_period}}                                     |
| Lag in Data Release    | {{lag_in_data_release}}                                    |
| Data Release Timing    | {{data_release_timing}}                                    |
| Seasonal Adjustment    | {{seasonal_adjustment}}                                    |
| Units                  | {{units}}                                                  |
{% if data_series %}| Data Series            | {{data_series | join(', ')}}                                            |
{% endif %}| HTML Chart             | [HTML](../download_chart/{{pipeline_id}}/{{chart_id}}.html)    |
{% if excel_chart_exists %}| Excel Chart             | [Excel]({{excel_chart_download_path}})    |{% endif %}

## Dataframe Manifest

{% include "dataframe_manifest.md" %}

## Pipeline Manifest

{% include "pipeline_manifest.md" %}
