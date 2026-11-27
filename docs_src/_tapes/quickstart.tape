# The Quickstart: minimal manifest, chartbook run, commit, chartbook snapshot, chartbook ls
Output "/out/quickstart.mp4"
Output "/out/quickstart.webm"
Source "/tapes/_settings.tape"

Hide
Type `cp -r /src /work/my-pipeline && cd /work/my-pipeline && git init -q && git config user.email "you@example.com" && git config user.name "You" && export PS1='\[\e[38;5;75m\]my-pipeline\[\e[0m\] $ ' && clear` Enter
Sleep 500ms
Show

Type "head -n 13 chartbook.toml" Sleep 300ms Enter
Sleep 2.5s
Type "chartbook run" Sleep 300ms Enter
Wait+Screen@30s /Trust this folder/
Sleep 1s
Type "y" Enter
Wait+Screen@60s /built\./
Sleep 2s
Type `git add -A && git commit -qm "First pipeline" && chartbook snapshot` Sleep 300ms Enter
Wait+Screen@60s /Create one over your store/
Sleep 1s
Type "" Enter
Sleep 2.5s
Type "chartbook ls" Sleep 300ms Enter
Sleep 4s
