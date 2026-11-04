# The homepage's: what is in the catalog, what one dataset is, where its file is, and the data in Python
Output "/out/catalog.mp4"
Output "/out/catalog.webm"
Source "/tapes/_settings.tape"
Set Width 1300
Set Height 860

Hide
Source "/tapes/_tutorial_store.tape"
Type `export PS1='\[\e[38;5;75m\]~\[\e[0m\] $ ' && clear` Enter
Sleep 3s
Show

Type "chartbook ls dataframes" Sleep 300ms Enter
Sleep 3s
Hide
Type "clear" Enter
Sleep 300ms
Show
Type "chartbook get-docs macro_basics:macro_series" Sleep 300ms Enter
Sleep 7s
Hide
Type "clear" Enter
Sleep 300ms
Show
Type "chartbook path macro_basics:macro_series" Sleep 300ms Enter
Sleep 3s
Type "python" Sleep 300ms Enter
Wait+Screen@30s />>>/
Type "from chartbook import data" Enter
Sleep 800ms
Type `data.load("macro_basics:macro_series").tail(5).collect()` Sleep 300ms Enter
Sleep 6s
