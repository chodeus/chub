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


def _reaches(node, module_funcs, targets, _seen=None):
    """True if node calls any of `targets`, directly or via a same-module helper."""
    # One traversal for all three questions below. A direct-call check misses
    # notifications.py saving through _save_destinations, and misses a Depends
    # wrapper like _get_config / get_config_dep that loads config for you.
    if _called_names(node) & targets:
        return True
    seen = _seen if _seen is not None else set()
    for name in _called_names(node):
        helper = module_funcs.get(name)
        if helper is None or name in seen:
            continue
        seen.add(name)
        if _reaches(helper, module_funcs, targets, seen):
            return True
    return False


def _writes_config(node, module_funcs):
    """True if the handler reaches save_config, directly or via a same-module helper."""
    return _reaches(node, module_funcs, {"save_config"})


def _serialised(node, module_funcs):
    """True if the handler holds the config write lock, by decorator or `with`."""
    if any("config_write" in ast.unparse(d) for d in node.decorator_list):
        return True
    for n in ast.walk(node):
        if isinstance(n, ast.With) and any(
            "config_write_lock" in ast.unparse(item.context_expr) for item in n.items
        ):
            # Resolve helpers here too, or a lock body that saves via a helper
            # reads as unserialised.
            if any(_writes_config(stmt, module_funcs) for stmt in n.body):
                return True
    return False


CONFIG_READS = {"load_config", "get_config"}


def _reads_config_via_dependency(node, module_funcs):
    """True if config arrives as a Depends — resolved BEFORE any lock is taken."""
    defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d]
    for default in defaults:
        if not isinstance(default, ast.Call):
            continue
        if (getattr(default.func, "id", None) or "") != "Depends" or not default.args:
            continue
        target = ast.unparse(default.args[0])
        if target in CONFIG_READS:
            return True
        # A wrapper such as _get_config / get_config_dep reads config for you.
        helper = module_funcs.get(target)
        if helper is not None and _reaches(helper, module_funcs, CONFIG_READS):
            return True
    return False


def _label(path, node):
    return f"{path.relative_to(API_DIR.parent.parent)}:{node.lineno} {node.name}"


def test_every_config_writer_is_serialised():
    """A handler that reaches save_config must hold the config write lock."""
    offenders = [
        _label(path, node)
        for path, node, funcs in _routes()
        if _writes_config(node, funcs) and not _serialised(node, funcs)
    ]
    assert not offenders, (
        "Config load-modify-save must be serialised, or two concurrent writers "
        "lose one side's edit. Add @config_write, or wrap the span in "
        "`with config_write_lock():`\n  " + "\n  ".join(offenders)
    )


def test_config_writers_read_inside_the_lock():
    """A writer must load config in its own body, not via Depends."""
    offenders = [
        _label(path, node)
        for path, node, funcs in _routes()
        if _writes_config(node, funcs) and _reads_config_via_dependency(node, funcs)
    ]
    assert not offenders, (
        "FastAPI resolves Depends BEFORE the handler runs, so a Depends-supplied "
        "config is read outside the lock and two writers still lose an edit. "
        "Call load_config() in the body instead:\n  " + "\n  ".join(offenders)
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


DEPENDENCY_CASES = [
    ("direct", "config: C = Depends(get_config)", True),
    ("wrapper", "config: C = Depends(resolve_settings)", True),
    ("unrelated", "logger: Any = Depends(get_logger)", False),
]


@pytest.mark.parametrize(
    "label, param, expected", DEPENDENCY_CASES, ids=[c[0] for c in DEPENDENCY_CASES]
)
def test_dependency_detection_resolves_wrappers(label, param, expected):
    """A Depends wrapper that loads config counts as reading outside the lock."""
    module = ast.parse(
        "def get_config():\n"
        "    return load_config()\n"
        "def resolve_settings():\n"
        "    return load_config()\n"
        "def get_logger():\n"
        "    return None\n"
        f"def handler({param}):\n"
        "    save_config(config)\n"
    )
    funcs = _module_functions(module)
    assert _reads_config_via_dependency(funcs["handler"], funcs) is expected


@pytest.mark.parametrize("name", ["load_config", "save_config", "config_write", "config_write_lock"])
def test_helpers_the_guards_key_on_still_exist(name):
    """Known-answer control: the guards are vacuous if these helpers get renamed."""
    from backend.util import config

    assert hasattr(config, name), f"backend.util.config.{name} is gone — update the guards above"
