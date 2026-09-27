"""Run offline evals in a fresh interpreter with an isolated environment.

    python -m evals.offline [pytest arguments]
"""

import subprocess
import sys

from evals.isolation import ROOT, install


def main() -> int:
    scratch = install()
    args = sys.argv[1:] or ["-q", "evals/deterministic"]
    return subprocess.call(
        [sys.executable, "-m", "pytest", "--basetemp", str(scratch / "pytest"), *args],
        cwd=ROOT,
    )


if __name__ == "__main__":
    raise SystemExit(main())
