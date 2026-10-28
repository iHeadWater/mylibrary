"""Provider-free domain rules, contracts and constants.

Nothing in this package may import ``adapters``, ``application`` or
``subprocess``, and no concrete model provider may drive a branch here. The
check itself lives in ``tests/test_import_boundaries.py``.

One deliberate exception: ``source_access.py`` holds historical on-disk method
strings, one of which names a provider. Those are data contracts persisted in
old drafts, not provider bindings, and the guard exempts them per literal.
"""
