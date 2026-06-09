"""``python -m weatherbot`` entry point.

Delegates to :func:`weatherbot.cli.main` so ``python -m weatherbot --send-now``
runs the on-demand briefing pipeline (CONF-04).
"""

from __future__ import annotations

import sys

from weatherbot.cli import main

if __name__ == "__main__":
    sys.exit(main())
