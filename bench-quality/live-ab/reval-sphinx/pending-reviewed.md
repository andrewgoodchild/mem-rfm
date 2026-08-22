
<!-- ratified 2026-08-22 17:23:35 (approve-all, ratify_staged.py) -->

## Candidates from session bb2cb2e6
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `python -m pytest tests/test_ext_autodoc_configs.py tests/test_ext_autodoc.py -q 2>&1 | tail -3; flake8 sphinx/ext/autodoc/typehints.py && echo FLAKE8_OK` fails (command not found); use `git stash -q && python -m pytest "tests/test_ext_autodoc_configs.py::test_autodoc_typehints_description_with_documented_init" "tests/test_ext_autodoc.py::test_autodoc" -q 2>&1 | tail -3; git stash pop` instead.
