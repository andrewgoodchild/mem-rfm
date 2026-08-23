
<!-- ratified 2026-08-23 17:13:19 (approve-all, ratify_staged.py) -->

## Candidates from session cdf5d073
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `python -m pytest testing/code/test_excinfo.py testing/test_runner.py testing/test_terminal.py testing/test_junitxml.py testing/test_skipping.py -q -p no:cacheprovider 2>&1 | tail -8` fails (modulenotfounderror); use `python -m pytest testing/code/test_excinfo.py testing/test_runner.py testing/test_terminal.py testing/test_skipping.py testing/test_resultlog.py -q -p no:cacheprovider 2>&1 | tail -8` instead.

<!-- ratified 2026-08-23 17:23:28 (approve-all, ratify_staged.py) -->

## Candidates from session f71388fc
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `cd /tmp && timeout 60 pip download pytest==5.1.3 --no-deps --no-binary :all: -d /tmp/pytest513 2>&1 | tail -5` fails (command not found); use `cd /tmp && python -m pip download pytest==5.1.3 --no-deps --no-binary :all: -d /tmp/pytest513 2>&1 | tail -5` instead.
- In this project, `python -m pytest testing/test_conftest.py testing/test_config.py testing/test_collection.py testing/acceptance_test.py testing/test_pathlib.py -q -p no:cacheprovider 2>&1 | tail -8` fails (importerror); use `git stash push -- src/ >/dev/null && python -m pytest testing/test_conftest.py testing/test_config.py testing/test_collection.py testing/acceptance_test.py testing/test_pathlib.py -q -p no:cacheprovid` instead.

<!-- ratified 2026-08-23 17:29:03 (approve-all, ratify_staged.py) -->

## Candidates from session bd329bab
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `git log --oneline -20 --all --grep="5.2.3" ; echo ---; git tag | tail -5` fails (importerror); use `git log --all --oneline --grep="6194" | head -20` instead.
- In this project, `python -m pytest testing/python/collect.py testing/test_skipping.py testing/acceptance_test.py -q -p no:cacheprovider 2>&1 | tail -8` fails (importerror); use `python -m pytest testing/python/collect.py testing/test_skipping.py testing/acceptance_test.py -q -p no:cacheprovider 2>&1 | grep '^FAILED' | sort > /tmp/after.txt; git stash push -- src/ >/dev/null; ` instead.

<!-- ratified 2026-08-23 17:47:17 (approve-all, ratify_staged.py) -->

## Candidates from session c5d5780d
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `python -m pytest testing/ -q -p no:cacheprovider -x -q 2>&1 | tail -15` fails (importerror); use `python -m pytest testing/ -q -p no:cacheprovider --ignore=testing/test_junitxml.py 2>&1 | tail -15` instead.
