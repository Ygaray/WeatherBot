"""Reusable bot module boundary (final import root, D-01).

This package is the clean, app-agnostic core that future bots import. It carries
zero coupling to the WeatherBot application: the one-way dependency rule is that
the host app may import from here, but nothing here may ever import the app. That
boundary is enforced by the standing import-hygiene gates in
``tests/test_import_hygiene.py`` (a grimp import-graph assert, an isolated-import
smoke test, and an AST signature litmus) and re-run by every subsequent phase.

The subpackages — ``channels`` (the channel-agnostic delivery abstraction),
``reliability`` (retry/backoff primitives), and ``ports`` (host-supplied adapter
seams) — are scaffolded empty here; the real relocated code lands in later plans.
"""

from __future__ import annotations
