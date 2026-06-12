"""Tests for backend/modules/renameinatorr.py — static chunking and config helpers."""

from copy import deepcopy
from types import SimpleNamespace


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
    chunks = Renameinatorr.get_untagged_chunks_for_run(
        items, 99, 10, False, StubLogger()
    )
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
    chunks = Renameinatorr.get_untagged_chunks_for_run(
        items, 99, 10, False, StubLogger()
    )
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


# --- ignore_tags filtering in process_instance ---


class FakeApp:
    instance_name = "radarr_main"

    def __init__(self, media, tags):
        self._media = media
        self._tags = tags
        self.created_tags = []
        self.fetched_rename_ids = []

    def get_all_media(self):
        return self._media

    def get_all_tags(self):
        return self._tags

    def create_tag(self, name):
        self.created_tags.append(name)
        return 99

    def get_tag_id_from_name(self, name):
        # The ignore path must never resolve tags through here (it creates
        # missing tags as a side effect).
        self.created_tags.append(name)
        return 99

    def get_rename_list(self, media_id, threadsafe=False):
        self.fetched_rename_ids.append(media_id)
        return []


def _ignore_cfg(ignore_tags):
    return SimpleNamespace(
        count=0,
        radarr_count=0,
        sonarr_count=0,
        tag_name="",
        ignore_tags=ignore_tags,
        enable_batching=False,
        dry_run=True,
        rename_folders=False,
        refresh_before_rename=False,
    )


def _run_process_instance(app, cfg):
    m = object.__new__(Renameinatorr)
    m._cancel_event = None
    m.process_instance(app, "radarr", cfg, StubLogger())


def _item(media_id, tags):
    return {
        "media_id": media_id,
        "tags": tags,
        "title": f"Item {media_id}",
        "year": 2020,
        "path_name": f"Item {media_id}",
    }


def test_ignore_tags_comma_separated_skips_any_match():
    media = [
        _item(1, [1]),
        _item(2, [2]),
        _item(3, [3]),
        _item(4, []),
    ]
    tags = [
        {"id": 1, "label": "skip-me"},
        {"id": 2, "label": "also-this"},
        {"id": 3, "label": "keep"},
    ]
    app = FakeApp(media, tags)
    _run_process_instance(app, _ignore_cfg("skip-me, also-this"))
    # Items 1 and 2 carry an ignore tag; only 3 and 4 are processed.
    assert sorted(app.fetched_rename_ids) == [3, 4]
    assert app.created_tags == []


def test_ignore_tags_single_tag_still_works():
    media = [
        _item(1, [1]),
        _item(2, []),
    ]
    tags = [{"id": 1, "label": "skip-me"}]
    app = FakeApp(media, tags)
    _run_process_instance(app, _ignore_cfg("skip-me"))
    assert app.fetched_rename_ids == [2]


def test_ignore_tags_missing_tag_is_not_created():
    media = [_item(1, [])]
    app = FakeApp(media, tags=[])
    _run_process_instance(app, _ignore_cfg("does-not-exist"))
    # Nothing filtered, and crucially the tag was not created in the ARR.
    assert app.fetched_rename_ids == [1]
    assert app.created_tags == []


# --- ignore tags survive the tag-cycle reset ---


class ResetFakeApp:
    """Stub that models the 'all tagged -> clear and re-fetch' reset path:
    remove_tags actually strips the tag from the backing store so the
    subsequent get_all_media() re-fetch reflects the cleared state.
    """

    instance_name = "radarr_main"

    def __init__(self, media, tags):
        self._media = media
        self._tags = tags
        self.fetched_rename_ids = []
        self.tagged_ids = []
        self.removed_ids = []

    def get_all_media(self):
        # Fresh copies so the module can't mutate our backing fixtures.
        return deepcopy(self._media)

    def get_all_tags(self):
        return self._tags

    def get_tag_id_from_name(self, name):
        for t in self._tags:
            if t["label"] == name:
                return t["id"]
        return None

    def remove_tags(self, ids, tag_id):
        self.removed_ids.extend(ids)
        for item in self._media:
            if item["media_id"] in ids and tag_id in item["tags"]:
                item["tags"].remove(tag_id)

    def add_tags(self, ids, tag_id):
        self.tagged_ids.extend(ids)

    def rename_media(self, ids):
        pass

    def refresh_items(self, ids):
        return {"id": 1}

    def wait_for_command(self, command_id):
        return True

    def get_rename_list(self, media_id, threadsafe=False):
        self.fetched_rename_ids.append(media_id)
        return []


def _reset_cfg():
    return SimpleNamespace(
        count=0,
        radarr_count=0,
        sonarr_count=0,
        tag_name="renamed",
        ignore_tags="norename",
        enable_batching=False,
        dry_run=True,
        rename_folders=False,
        refresh_before_rename=False,
    )


def test_ignore_tags_survive_tag_cycle_reset():
    # Non-ignored item already tagged 'renamed' (id 50); an ignored item
    # carries 'norename' (id 1) and never the 'renamed' tag. With every
    # non-ignored item tagged, process_instance hits the reset path: it
    # clears tags and re-fetches the whole library. The ignored item must
    # NOT be swept back into processing on that re-fetch.
    tags = [{"id": 50, "label": "renamed"}, {"id": 1, "label": "norename"}]
    media = [_item(1, [50]), _item(2, [1])]
    app = ResetFakeApp(media, tags)
    _run_process_instance(app, _reset_cfg())
    # The 'norename' item (id 2) is never processed; the cleared item is.
    assert 2 not in app.fetched_rename_ids
    assert app.fetched_rename_ids == [1]
