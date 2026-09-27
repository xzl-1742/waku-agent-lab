import os
import sys
from pathlib import Path

# evals/ sits next to waku/, not inside it — make both importable when
# running `pytest evals` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# This executes BEFORE test modules import config (an autouse fixture is too late).
# Live suites require an explicit opt-in; the offline launcher clears that flag.
if os.environ.get("WAKU_RUN_LIVE_EVALS") != "1":
    from evals.isolation import install

    _scratch = install()

    def pytest_configure(config):
        if not config.option.basetemp:
            config.option.basetemp = str(_scratch / "pytest")
