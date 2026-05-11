"""Tests for backend/modules/renameinatorr.py — static chunking and config helpers."""

from types import SimpleNamespace

import pytest

from backend.modules.renameinatorr import Renameinatorr


class StubLogger:
    def __init__(self):
        self.msgs = []

    def debug(self, *a, **kw):
        self.msgs.append(("debug",) + a)

    def info(self, *a, **kw):
        self.msgs.append(("info",) + a)

    def warning(self, *a, **kw):
        self.msgs.append(("warning",) + a)

    def error(self, *a, **kw):
        self.msgs.append(("error",) + a)


# --- get_count_for_instance_type ---


def test_get_count_uses_default_count():
    cfg = SimpleNamespace(count=10, radarr_count=0, sonarr_count=0)
    assert Renameinatorr.get_count_for_instance_type(cfg, "radarr", StubLogger()) == 10


def test_get_count_overridden_by_radarr_count():
    cfg = SimpleNamespace(count=10, radarr_count=50, sonarr_count=0)
    assert Renameinatorr.get_count_for_instance_type(cfg, "radarr", StubLogger()) == 50


def test_get_count_overridden_by_sonarr_count():
    cfg = SimpleNamespace(count=10, radarr_count=0, sonarr_count=25)
    assert Renameinatorr.get_count_for_instance_type(cfg, "sonarr", StubLogger()) == 25


def test_get_count_radarr_override_ignored_for_sonarr():
    cfg = SimpleNamespace(count=10, radarr_count=99, sonarr_count=0)
    assert Renameinatorr.get_count_for_instance_type(cfg, "sonarr", StubLogger()) == 10


# --- get_chunks_for_run ---


def test_get_chunks_evenly_split():
    items = [{"id": i} for i in range(10)]
    chunks = Renameinatorr.get_chunks_for_run(items, 5, StubLogger())
    assert len(chunks) == 2
    assert chunks[0] == items[:5]
    assert chunks[1] == items[5:]


def test_get_chunks_partial_last_chunk():
    items = [{"id": i} for i in range(7)]
    chunks = Renameinatorr.get_chunks_for_run(items, 3, StubLogger())
    assert len(chunks) == 3
    assert len(chunks[-1]) == 1


def test_get_chunks_empty_input():
    chunks = Renameinatorr.get_chunks_for_run([], 5, StubLogger())
    assert chunks == []


def test_get_chunks_size_larger_than_list():
    items = [{"id": 1}, {"id": 2}]
    chunks = Renameinatorr.get_chunks_for_run(items, 100, StubLogger())
    assert len(chunks) == 1
    assert chunks[0] == items


# --- get_untagged_chunks_for_run ---


def test_untagged_chunks_filters_tagged_items():
    items = [
        {"id": 1, "tags": []},
        {"id": 2, "tags": [99]},
        {"id": 3, "tags": [1, 2]},
    ]
    chunks = Renameinatorr.get_untagged_chunks_for_run(items, 99, 10, False, StubLogger())
    # Only items 1 and 3 are untagged
    assert len(chunks) == 1
    untagged_ids = [item["id"] for item in chunks[0]]
    assert 2 not in untagged_ids
    assert set(untagged_ids) == {1, 3}


def test_untagged_chunks_returns_empty_when_all_tagged():
    items = [
        {"id": 1, "tags": [99]},
        {"id": 2, "tags": [99]},
    ]
    chunks = Renameinatorr.get_untagged_chunks_for_run(items, 99, 10, False, StubLogger())
    assert chunks == []


def test_untagged_chunks_single_run_mode():
    items = [{"id": i, "tags": []} for i in range(50)]
    # all_in_single_run=True returns a single chunk
    chunks = Renameinatorr.get_untagged_chunks_for_run(
        items, 99, 10, True, StubLogger()
    )
    assert len(chunks) == 1
    assert len(chunks[0]) == 50


def test_untagged_chunks_batches_when_size_set():
    items = [{"id": i, "tags": []} for i in range(25)]
    chunks = Renameinatorr.get_untagged_chunks_for_run(
        items, 99, 10, False, StubLogger()
    )
    assert len(chunks) == 3
    assert sum(len(c) for c in chunks) == 25
