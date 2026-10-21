"""Kinds of store beyond the folder, each behind an install extra.

:mod:`chartbook.store` says what a store is and holds the folder store, the
one `pip install chartbook` gives you. The modules here are the other
kinds, found by the scheme of the store's URL through the entry-point
group ``chartbook.stores`` (see :func:`chartbook.store.store_for_url`).
Each needs a library the base install does not bring, named by the extra
that installs it:

======== ======================= ===========================
Scheme   Module                  Installs with
======== ======================= ===========================
``s3``   :mod:`chartbook.stores.s3`  ``pip install chartbook[s3]``
======== ======================= ===========================

Importing this package imports none of those libraries.
"""
