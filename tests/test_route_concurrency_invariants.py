"""Static guards on how backend/api route handlers are declared.
An `async def` that never awaits holds the event loop; `def` goes to the threadpool.
"""

import ast
import pathlib

import pytest

API_DIR = pathlib.Path(__file__).resolve().parent.parent / "backend" / "api"
ROUTE_DECORATORS = (".get(", ".post(", ".put(", ".delete(", ".patch(")


def _routes():
    """Yield (path, handler node, that module's functions) for every decorated route."""
    for path in sorted(API_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text())
        funcs = _module_functions(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = [ast.unparse(d) for d in node.decorator_list]
            if any(any(m in d for m in ROUTE_DECORATORS) for d in decorators):
                yield path, node, funcs


def _module_functions(tree):
    return {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _awaits(node):
    return [
        n.lineno
        for n in ast.walk(node)
        if isinstance(n, (ast.Await, ast.AsyncFor, ast.AsyncWith))
    ]


def _calls_named(node, name):
    return [
        n.lineno
        for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and name in (getattr(n.func, "id", None), getattr(n.func, "attr", None))
    ]


def _called_names(node):
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            out.add(getattr(n.func, "id", None) or getattr(n.func, "attr", None))
    return out - {None}


def _writes_config(node, module_funcs, _seen=None):
    """True if the handler reaches save_config, directly or via a same-module helper."""
    # notifications.py routes save through _save_destinations; a direct-call check
    # misses those and lets an unserialised writer through.
    if _calls_named(node, "save_config"):
        return True
    seen = _seen if _seen is not None else set()
    for name in _called_names(node):
        helper = module_funcs.get(name)
        if helper is None or name in seen:
            continue
        seen.add(name)
        if _writes_config(helper, module_funcs, seen):
            return True
    return False


def _serialised(node):
    """True if the handler holds the config write lock, by decorator or `with`."""
    if any("config_write" in ast.unparse(d) for d in node.decorator_list):
        return True
    for n in ast.walk(node):
        if isinstance(n, ast.With) and any(
            "config_write_lock" in ast.unparse(item.context_expr) for item in n.items
        ):
            saves = [
                ln
                for body in n.body
                for ln in _calls_named(body, "save_config")
            ]
            if saves:
                return True
    return False


def _label(path, node):
    return f"{path.relative_to(API_DIR.parent.parent)}:{node.lineno} {node.name}"


def test_every_config_writer_is_serialised():
    """A handler that reaches save_config must hold the config write lock."""
    offenders = [
        _label(path, node)
        for path, node, funcs in _routes()
        if _writes_config(node, funcs) and not _serialised(node)
    ]
    assert not offenders, (
        "Config load-modify-save must be serialised, or two concurrent writers "
        "lose one side's edit. Add @config_write, or wrap the span in "
        "`with config_write_lock():`\n  " + "\n  ".join(offenders)
    )


def test_no_event_loop_blocking_handlers():
    """No handler may be `async def` without an await; those belong on the threadpool."""
    offenders = [
        _label(path, node)
        for path, node, _funcs in _routes()
        if isinstance(node, ast.AsyncFunctionDef) and not _awaits(node)
    ]
    assert not offenders, (
        "These handlers are `async def` but never await, so they block the event "
        "loop and stall every other request. Declare them `def` instead:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("name", ["load_config", "save_config", "config_write", "config_write_lock"])
def test_helpers_the_guards_key_on_still_exist(name):
    """Known-answer control: the guards are vacuous if these helpers get renamed."""
    from backend.util import config

    assert hasattr(config, name), f"backend.util.config.{name} is gone — update the guards above"
