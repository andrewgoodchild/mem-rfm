
<!-- ratified 2026-08-17 18:07:21 (approve-all, ratify_staged.py) -->

## Candidates from session 4c6051cd
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `cd /tmp/sphinx_type_hint_links && cat <<'EOF' >docs/conf.py` fails (no such file or directory); use `cd /tmp/sphinx_type_hint_links && printf 'def setup(app):\n    return {"version": "stub", "parallel_read_safe": True}\n' > stubs/alabaster.py && \` instead.
- In this project, `PYTHONPATH=/tmp/sphinx_type_hint_links/stubs python -m pytest tests/test_ext_autodoc_configs.py::test_autodoc_typehints_signature -q 2>&1 | grep -A5 'ModuleNotFound\|Error' | head -20` fails (modulenotfounderror); use `PYTHONPATH=/tmp/sphinx_type_hint_links/stubs python -m pytest tests/test_domain_py.py tests/test_ext_autodoc_configs.py tests/test_pycode_ast.py -q 2>&1 | tail -4` instead.
