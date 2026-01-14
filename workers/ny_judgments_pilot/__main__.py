"""
NY Judgments Pilot Worker - Canonical Entrypoint

This module enables running the worker via:
    python -m workers.ny_judgments_pilot

This is the ONLY supported way to run this worker.
Do not use standalone scripts or import main() directly.
"""

import sys

from .main import run


def main() -> None:
    """
    Canonical entrypoint for the NY Judgments Pilot Worker.

    Executes the synchronous worker loop and exits with appropriate code.
    """
    exit_code = run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
