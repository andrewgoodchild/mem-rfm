
<!-- ratified 2026-08-22 19:29:31 (approve-all, ratify_staged.py) -->

## Candidates from session 14dd9a47
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `python - <<'EOF'` fails (pkg_resources); use `which -a python python3 2>/dev/null; echo "---"; python -c "import sys; print(sys.executable, sys.version)"; echo "---"; ls -d .venv venv .tox 2>/dev/null; ls -d ../.venv ../../.venv ../../../.venv 2>` instead.

<!-- ratified 2026-08-22 19:52:28 (approve-all, ratify_staged.py) -->

## Candidates from session d463ea77
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `python - <<'EOF'` fails (pkg_resources); use `which -a python python3 2>/dev/null; echo "---"; python --version; python3 --version; echo "--- venvs:"; ls -d /Users/andrewgoodchild/code/mem-rfm/bench-quality/live-ab/clones/xarray-rfm/.venv /Users/` instead.
- In this project, `python -m pip list 2>/dev/null | grep -iE "^(setuptools|pip|pytest|xarray|numpy|pandas) " ; echo "--- import pkg_resources:"; python -c "import pkg_resources; print('ok')" 2>&1 | tail -1; echo "--- py` fails (pkg_resources); use `echo "--- pip:"; python -m pip --version 2>&1 | tail -1; echo "--- site-packages:"; ls "$VIRTUAL_ENV/lib/python3.9/site-packages" 2>/dev/null | grep -iE "setuptools|pkg_resources|pytest|xarray|numpy|p` instead.

<!-- ratified 2026-08-22 19:54:55 (approve-all, ratify_staged.py) -->

## Candidates from session 5ba9348c
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `python -m pytest xarray/tests/test_weighted.py -q -x 2>&1 | head -40` fails (importerror); use `echo "--- python: $(which python)"; echo "--- VIRTUAL_ENV: $VIRTUAL_ENV"; echo "--- pip:"; python -m pip --version 2>&1 | tail -1; echo "--- site-packages:"; ls "$(python -c 'import sysconfig; print(s` instead.
- In this project, `python /tmp/repro_gh4074.py 2>&1 | tail -20` fails (pkg_resources); use `python -c "import sys; print(sys.version)"; python -m pip download setuptools --no-deps -d /tmp/_st_check -q 2>&1 | tail -2; echo "exit=$?"` instead.

<!-- ratified 2026-08-22 20:32:58 (approve-all, ratify_staged.py) -->

## Candidates from session 9de16601
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `python -m pytest xarray/tests/test_merge.py -q -x -W ignore::DeprecationWarning -p no:cacheprovider 2>&1 | tail -8` fails (pkg_resources); use `python -m pytest xarray/tests/test_dataset.py -q -W ignore::DeprecationWarning -p no:cacheprovider -k "merge or attrs" 2>&1 | tail -3` instead.

<!-- ratified 2026-08-22 20:58:51 (approve-all, ratify_staged.py) -->

## Candidates from session 2c673749
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `python /tmp/repro_loc_method.py 2>&1 | tail -40` fails (pkg_resources); use `python -m pytest xarray/tests/test_dataarray.py -q -W ignore::DeprecationWarning -W ignore::UserWarning -p no:cacheprovider -k "loc or sel or isel or indexing" 2>&1 | tail -8` instead.

<!-- ratified 2026-08-22 21:02:49 (approve-all, ratify_staged.py) -->

## Candidates from session 45e17de2
<!-- Proposed, not saved. Review, then keep the useful ones
     with memory_save. -->

- In this project, `python -m pytest /tmp/test_unsigned_false_repro.py -q -W ignore::DeprecationWarning -p no:cacheprovider 2>&1 | tail -15` fails (pkg_resources); use `python -m pytest xarray/tests/test_coding.py xarray/tests/test_conventions.py -q -W ignore::DeprecationWarning -W ignore::UserWarning -p no:cacheprovider 2>&1 | tail -5; echo "--- backends unsigned:";` instead.
