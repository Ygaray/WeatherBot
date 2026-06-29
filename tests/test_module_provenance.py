"""Self-disciplined unit test for ``_module_provenance()`` (Phase 28-03, D-06).

The provenance reader announces the *deployed* module sha at daemon startup by
reading the installed ``yahir-reusable-bot`` dist-info ``direct_url.json`` (PEP
610) via ``importlib.metadata``. A guard is only trustworthy if a deliberately
constructed input is proven to drive it (the self-proof discipline from
``tests/test_import_hygiene.py``), so this test feeds BOTH install shapes:

- a **git install** (``vcs_info.commit_id`` present) — asserts the reader
  surfaces the embedded sha + tag and reports ``editable == "False"``;
- an **editable install** (``dir_info.editable = true``, no ``vcs_info``) —
  asserts ``editable == "True"`` and an empty sha (the dev-tree tripwire);
- a **missing record** (``read_text`` returns ``None``) — asserts the reader
  returns the version with empty sha/ref and does NOT raise (startup-safety).

The ``direct_url.json`` shapes used here are the ones EMPIRICALLY CONFIRMED by
the 28-01 spike (see 28-01-SUMMARY.md): a uv git install writes
``vcs_info.commit_id`` + ``vcs_info.requested_revision`` and NO ``dir_info`` key;
an editable install carries ``dir_info.editable = true``.
"""

from __future__ import annotations

import json
from unittest import mock

from weatherbot import cli

# The exact git-install shape observed in the 28-01 spike venv (field names
# confirmed against uv 0.11.19 — vcs_info.commit_id matched git rev-parse HEAD
# byte-for-byte; no dir_info key on a git install).
_GIT_SHA = "138a907d57ac1d1d8499399b019f1509e43d02f1"
_GIT_DIRECT_URL = {
    "url": "file:///home/yahir/Projects/YahirReusableBot",
    "vcs_info": {
        "vcs": "git",
        "commit_id": _GIT_SHA,
        "requested_revision": "v0.1.0",
    },
}

# The editable-install shape (dir_info.editable=true, no vcs_info) — the
# dev-tree overlay tripwire.
_EDITABLE_DIRECT_URL = {
    "url": "file:///home/yahir/Projects/YahirReusableBot",
    "dir_info": {"editable": True},
}


def _provenance_with(direct_url_raw, version="0.1.0"):
    """Drive ``_module_provenance`` with a stubbed dist-info read.

    Patches ``Distribution.from_name`` (so ``read_text("direct_url.json")``
    returns ``direct_url_raw``) and ``version`` so the test never touches a
    live install.
    """
    fake_dist = mock.Mock()
    fake_dist.read_text.return_value = direct_url_raw
    with (
        mock.patch.object(
            cli.Distribution, "from_name", return_value=fake_dist
        ) as from_name,
        mock.patch.object(cli, "version", return_value=version) as ver,
    ):
        result = cli._module_provenance()
    # The reader must read the PEP 610 record and the dist version.
    fake_dist.read_text.assert_called_once_with("direct_url.json")
    from_name.assert_called_once_with("yahir-reusable-bot")
    ver.assert_called_once_with("yahir-reusable-bot")
    return result


def test_git_install_shape_surfaces_embedded_sha_and_tag():
    """A git install: the reader surfaces the resolved sha + tag, editable False."""
    result = _provenance_with(json.dumps(_GIT_DIRECT_URL))

    assert result == {
        "module_version": "0.1.0",
        "module_sha": _GIT_SHA,
        "module_ref": "v0.1.0",
        "editable": "False",
    }


def test_editable_install_shape_flags_dev_tree_with_empty_sha():
    """An editable install: editable == 'True', sha empty (the dev-tree tripwire)."""
    result = _provenance_with(json.dumps(_EDITABLE_DIRECT_URL))

    assert result["editable"] == "True"
    assert result["module_sha"] == ""
    assert result["module_ref"] == ""
    assert result["module_version"] == "0.1.0"


def test_missing_direct_url_record_does_not_raise_and_yields_empty_sha():
    """A wheel install with no direct_url.json: empty sha/ref, no raise (startup-safety)."""
    # read_text returns None when the dist-info has no direct_url.json record.
    result = _provenance_with(None)

    assert result == {
        "module_version": "0.1.0",
        "module_sha": "",
        "module_ref": "",
        "editable": "False",
    }
