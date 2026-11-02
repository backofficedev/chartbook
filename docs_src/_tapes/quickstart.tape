# The Quickstart: three files, the script that makes the data and the chart, the site, the record
Output "/out/quickstart.mp4"
Output "/out/quickstart.webm"
Source "/tapes/_settings.tape"

Hide
Type `cp -r /src /work/my-pipeline && cd /work/my-pipeline && git init -q && export PS1='\[\e[38;5;75m\]my-pipeline\[\e[0m\] $ ' && clear` Enter
Sleep 500ms
Show

Type "head -n 11 chartbook.toml" Sleep 300ms Enter
Sleep 2.5s
Type "python src/build_chart.py && ls _data _output" Sleep 300ms Enter
Wait+Screen@30s /random_walks_wide.png/
Sleep 2s
Type "clear && chartbook docs build" Sleep 300ms Enter
Wait+Screen@30s /Trust this folder/
Sleep 1.5s
Type "y" Enter
Wait+Screen@90s /Successfully generated/
Sleep 2s
Type `clear && jq -c '.records[] | select(.kind == "Dataframe" or .kind == "Chart") | {id, content_hash, inputs}' docs/index.json` Sleep 300ms Enter
Sleep 5s
