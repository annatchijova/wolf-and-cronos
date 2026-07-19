"""
Session-wide test isolation for CORVUS's default, environment-driven paths.

corvus.config.Config() falls back to real paths under the developer's home
directory (~/.corvus/memory.db, ~/.corvus/bundles) when nothing overrides
them. Some modules construct a Config() at import time (corvus/mcp_server.py
builds its module-level _config, _analyzer, and _verdict_engine singletons
this way), so overriding the environment inside a fixture can run too late —
after that module has already been imported and its Config() already
resolved to the real default.

Setting the environment at this file's own module level guarantees it runs
before pytest imports any test module, since conftest.py files are always
loaded before the tests they configure.

This became load-bearing once corvus.verdict.engine.VerdictEngine started
actually calling seal_bundle() for CRITICAL verdicts (previously a no-op in
practice: nothing called it, so a bare Config() was harmless in tests).
"""
import atexit
import os
import shutil
import tempfile

_TEST_HOME = tempfile.mkdtemp(prefix="corvus-test-home-")
os.environ.setdefault("CORVUS_BUNDLE_DIR", os.path.join(_TEST_HOME, "bundles"))
os.environ.setdefault("CORVUS_DB_PATH", os.path.join(_TEST_HOME, "memory.db"))

atexit.register(shutil.rmtree, _TEST_HOME, True)
