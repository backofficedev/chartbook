# The tutorial's first steps: a pipeline cloned, built and snapshotted, a catalog made and built, and listed
Output "/out/tutorial.mp4"
Output "/out/tutorial.webm"
Source "/tapes/_settings.tape"

Hide
Type `mkdir -p /work/tutorial && cd /work/tutorial && export PS1='\[\e[38;5;75m\]tutorial\[\e[0m\] $ ' && clear` Enter
Sleep 500ms
Show

Type "git clone https://github.com/backofficedev/treasury_curve" Sleep 300ms Enter
Wait+Screen@60s /done\./
Sleep 1s
Type "chartbook trust" Sleep 300ms Enter
Sleep 2s
Type "cd treasury_curve && chartbook run --snapshot" Sleep 300ms Enter
Wait+Screen@30s /build/
Sleep 2s
Hide
Wait+Screen@600s /Create one over your store/
Show
Sleep 2s
Type "" Enter
Sleep 3s
Type "clear && cd .. && chartbook catalog build" Sleep 300ms Enter
Wait+Screen@300s /catalog open/
Sleep 2s
Type "clear && chartbook ls" Sleep 300ms Enter
Sleep 5s
