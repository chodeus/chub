"""Tests for backend/util/base_module.py — ChubModule registry lookup + cancel events."""

import threading

import pytest

from backend.modules import MODULES
from backend.util.base_module import ChubModule


def test_module_name_lookup_for_each_registered():
    """Every registered class should resolve back to its key via _get_module_name."""
    for key, cls in MODULES.items():
        instance = object.__new__(cls)
        assert instance._get_module_name() == key


def test_unregistered_subclass_raises_lookup():
    class Rogue(ChubModule):
        def run(self):
            pass

    instance = object.__new__(Rogue)
    with pytest.raises(LookupError):
        instance._get_module_name()


def test_cancel_event_starts_unset():
    cls = next(iter(MODULES.values()))
    instance = object.__new__(cls)
    instance._cancel_event = None
    assert instance.is_cancelled() is False


def test_cancel_event_signals():
    cls = next(iter(MODULES.values()))
    instance = object.__new__(cls)
    event = threading.Event()
    instance.set_cancel_event(event)
    assert instance.is_cancelled() is False
    event.set()
    assert instance.is_cancelled() is True
