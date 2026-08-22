
<!-- ratified 2026-08-22 13:32:45 (approve-all, ratify_staged.py) -->

## Candidates from session d2f290a4
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `PYTHONPATH=/tmp/sphinx_type_hint_links/stubs python -m pytest tests/test_util_inspect.py::test_isproperty -q 2>&1 | grep -B2 -A2 'FileNotFoundError' | head -20` fails (no such file or directory); use `PYTHONPATH=/tmp/sphinx_type_hint_links/stubs python -m pytest tests/test_ext_autodoc.py tests/test_ext_autodoc_configs.py tests/test_domain_py.py tests/test_ext_autodoc_autofunction.py tests/test_ext_` instead.
