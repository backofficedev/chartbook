# What an agent runs: what is there, what it is, then build on it and check where it came from
Output "/out/agent.mp4"
Output "/out/agent.webm"
Source "/tapes/_settings.tape"

Hide
Type `cd /work && cp /zip/chartbook-tutorial-store.zip . && unzip -q chartbook-tutorial-store.zip && chartbook store import chartbook-tutorial-store > /dev/null && chartbook catalog init --title "My Catalog" > /dev/null` Enter
Type `cp -r /src /work/my-pipeline && cd /work/my-pipeline && git init -q && export PS1='\[\e[38;5;75m\]my-pipeline\[\e[0m\] $ ' && clear` Enter
Sleep 3s
Show

Type `chartbook ls --json | jq -c '.[] | {kind, id}'` Sleep 300ms Enter
Sleep 3.5s
Type "chartbook get-docs rate_outlook:model/spread_ar1" Sleep 300ms Enter
Sleep 4s
Type "clear && chartbook add tutorial/treasury_curve" Sleep 300ms Enter
Wait+Screen@60s /Wrote chartbook.lock/
Sleep 2.5s
Type "chartbook lineage" Sleep 300ms Enter
Sleep 5s
