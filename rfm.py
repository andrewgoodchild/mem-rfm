"""Repository-local alias for the engine, which ships as `mem_rfm`.

The engine is mem_rfm.py (PyPI: mem-rfm). It was rfm.py until it was
published, but a top-level `rfm` module already exists on PyPI (an
unrelated customer-segmentation package), so the installed import name is
mem_rfm. This alias keeps `import rfm` working for the integration, the
benchmarks and the tests in this repository; it makes `rfm` the very same
module object, private names and module state included. It is not part of
the published package.
"""
import sys

import mem_rfm

sys.modules[__name__] = mem_rfm
