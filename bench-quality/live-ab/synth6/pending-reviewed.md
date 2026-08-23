
<!-- ratified 2026-08-23 18:02:35 (approve-all, ratify_staged.py) -->

## Candidates from session 904498f8
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `python -m pytest testing/test_reports.py testing/test_runner.py testing/code/test_excinfo.py testing/test_junitxml.py -q 2>&1 | tail -8` fails (modulenotfounderror); use `python -m pytest testing/test_reports.py testing/test_runner.py testing/code/test_excinfo.py testing/test_terminal.py -q 2>&1 | tail -8` instead.

<!-- ratified 2026-08-23 18:23:14 (approve-all, ratify_staged.py) -->

## Candidates from session 70969b5e
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `git stash -q && python -m pytest "testing/python/collect.py::TestModule::test_import_prepend_append" "testing/python/collect.py::TestTracebackCutting::test_filter_traceback_path_no_longer_valid" -q 2>` fails (modulenotfounderror); use `python -m pytest testing/acceptance_test.py testing/test_runner.py testing/python/fixtures.py testing/test_terminal.py -q 2>&1 | grep -E "^(FAILED|ERROR)" | sort > /tmp/after.txt; git stash -q; python` instead.

<!-- ratified 2026-08-23 18:27:04 (approve-all, ratify_staged.py) -->

## Candidates from session 1e58219a
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `python -m pytest testing/test_unittest.py testing/python/fixtures.py testing/test_nose.py testing/acceptance_test.py -q -p no:randomly 2>&1 | tail -12` fails (importerror); use `python -m pytest testing/test_unittest.py testing/python/fixtures.py testing/test_nose.py testing/acceptance_test.py -q -p no:randomly 2>&1 | grep -E "^FAILED" | sort > /tmp/after.txt; git stash -q; p` instead.

<!-- ratified 2026-08-23 18:40:03 (approve-all, ratify_staged.py) -->

## Candidates from session 751bf9f2
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `python -m pytest testing/ -q -p no:randomly -x --ignore=testing/test_debugging.py 2>&1 | tail -15` fails (importerror); use `python -m pytest testing/ -q -p no:randomly --ignore=testing/test_junitxml.py 2>&1 | tail -15` instead.
