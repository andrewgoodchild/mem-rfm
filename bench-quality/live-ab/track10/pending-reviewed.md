
<!-- ratified 2026-08-24 20:19:28 (approve-all, ratify_staged.py) -->
<!-- Track 10 store: haiku v2 extractions from 9 held-in xarray tasks, consolidated 11 -> 5 -->
- black, flake8, mypy, and isort are not installed in the xarray development venv. Code should follow black's formatting conventions with 88-column line length (black standard). Type checking and linting require manual verification or installing these tools separately.
- dask is not installed in the xarray test environment. Dask-chunked parametrizations are skipped (~97 tests) during pytest runs on xarray/tests/. This is expected and does not indicate a test failure.
- setuptools 82 no longer ships pkg_resources. In this xarray venv, `import xarray` fails immediately without it. Workaround: add a pkg_resources shim to PYTHONPATH (which may generate harmless deprecation warnings during test runs). The venv also lacks pip.
- Running xarray tests with NumPy ≥1.22 generates a pre-existing DeprecationWarning in Variable.quantile about nanpercentile's interpolation= argument. This is safe to ignore generally, but the test_quantile_interpolation_deprecated test asserts on it—avoid running with `-W ignore::DeprecationWarning` as it will suppress the warning and cause the test to fail.
- The full test_dataset.py and test_dataarray.py test suite modules run in approximately 5 seconds on the xarray repo. When running tests during development, there is no need to use -k filters to subset tests—the full suite is fast enough to run without subsetting.
