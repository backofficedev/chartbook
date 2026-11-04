# What the tapes that show a catalog share: the tutorial's three pipelines, cloned from GitHub,
# built and snapshotted into the store, as the tutorial's first steps do (hidden: it takes minutes).
# The catalog is made first, so that no snapshot stops to offer one
Type `cd /work && export CHARTBOOK_TRUST=all && chartbook catalog init > /dev/null && git clone -q https://github.com/backofficedev/treasury_curve && git clone -q https://github.com/backofficedev/macro_basics && git clone -q https://github.com/backofficedev/rate_outlook` Enter
Type `(cd treasury_curve && chartbook run --snapshot) && (cd macro_basics && chartbook run --snapshot) && echo UPSTREAM-DONE` Enter
Wait+Screen@900s /UPSTREAM-DONE/
Type `(cd rate_outlook && chartbook update && chartbook run --snapshot) && echo DOWNSTREAM-DONE` Enter
Wait+Screen@600s /DOWNSTREAM-DONE/
Type `unset CHARTBOOK_TRUST && clear` Enter
