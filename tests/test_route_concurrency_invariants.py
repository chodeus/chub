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


def _module_functions(tree):
    return {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _writes_config(node, module_funcs, _seen=None):
    """True if the handler reaches save_config, directly or via a same-module helper."""
    # notifications.py routes save through _save_destinations; a direct-call check
    # misses those, converts them, and reintroduces the lost update this guards.
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


def _load_positions(node):
    """Lines where this handler's config read happens, earliest-first."""
    direct = _calls_named(node, "load_config")
    if direct:
        return direct
    # Config arriving as `Depends(get_config)` is read before the body runs, so
    # the whole body is inside the span. No read at all = a full overwrite.
    args = node.args
    for default in list(args.defaults) + list(args.kw_defaults):
        if default is not None and "get_config" in ast.unparse(default):
            return [node.lineno]
    return []


def _save_positions(node, module_funcs):
    """Lines in this handler where a config save happens — the helper call counts."""
    # A helper-mediated writer has no direct save_config line, so the span check
    # would compare against an empty list; the call to the helper is the save point.
    lines = list(_calls_named(node, "save_config"))
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
        helper = module_funcs.get(name)
        if helper is not None and helper is not node and _writes_config(helper, module_funcs):
            lines.append(call.lineno)
    return sorted(lines)


def _label(path, node):
    return f"{path.relative_to(API_DIR.parent.parent)}:{node.lineno} {node.name}"


def test_config_writers_are_async_and_never_await_mid_transaction():
    """Config writers stay async with an unbroken load→save span, so saves can't interleave."""
    offenders = []
    for path, node, funcs in _routes():
        if not _writes_config(node, funcs):
            continue
        if isinstance(node, ast.FunctionDef):
            offenders.append(f"{_label(path, node)} — is `def`, must be `async def`")
            continue
        saves = _save_positions(node, funcs)
        if not saves:
            offenders.append(
                f"{_label(path, node)} — reaches save_config but no save position "
                f"was located, so the span below cannot be checked"
            )
            continue
        loads = _load_positions(node)
        if not loads:
            continue  # writes a whole new config; no read to interleave with
        mid = [a for a in _awaits(node) if min(loads) < a < max(saves)]
        if mid:
            offenders.append(
                f"{_label(path, node)} — awaits at {mid} between load_config "
                f"(line {min(loads)}) and save_config (line {max(saves)})"
            )
    assert not offenders, (
        "Config read-modify-write must not be interruptible:\n  "
        + "\n  ".join(offenders)
    )


def test_no_new_event_loop_blocking_handlers():
    """Only config writers may be `async def` without an await; the rest go to the threadpool."""
    offenders = [
        _label(path, node)
        for path, node, funcs in _routes()
        if isinstance(node, ast.AsyncFunctionDef)
        and not _awaits(node)
        and not _writes_config(node, funcs)
    ]
    assert not offenders, (
        "These handlers are `async def` but never await, so they block the event "
        "loop and stall every other request. Declare them `def` instead:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("name", ["load_config", "save_config"])
def test_helpers_the_guards_key_on_still_exist(name):
    """Known-answer control: the guards are vacuous if these helpers get renamed."""
    from backend.util import config

    assert hasattr(config, name), f"backend.util.config.{name} is gone — update the guards above"
