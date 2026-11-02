# The tutorial's first steps: a catalog downloaded, imported, built and listed
Output "/out/tutorial.mp4"
Output "/out/tutorial.webm"
Source "/tapes/_settings.tape"

Hide
Type `cp /zip/chartbook-tutorial-store.zip /work/ && cd /work && export PS1='\[\e[38;5;75m\]~\[\e[0m\] $ ' && clear` Enter
Sleep 500ms
Show

Type "unzip -q chartbook-tutorial-store.zip" Sleep 300ms Enter
Sleep 1s
Type "chartbook store import chartbook-tutorial-store" Sleep 300ms Enter
Wait+Screen@60s /Imported/
Sleep 2.5s
Type `clear && chartbook catalog init --title "My Catalog" > /dev/null && chartbook catalog build` Sleep 300ms Enter
Wait+Screen@180s /catalog open/
Sleep 2s
Type "clear && chartbook ls" Sleep 300ms Enter
Sleep 5s
