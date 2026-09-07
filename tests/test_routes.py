"""Smoke tests for FastAPI route ordering and accessibility.

Verifies that named routes are not shadowed by catch-all path parameter routes.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.routing import APIRoute


def get_routes_for_router(module_path: str, router_attr: str = "router"):
    """Import a router module and extract its route definitions."""
    import importlib

    mod = importlib.import_module(module_path)
    router = getattr(mod, router_attr)
    return [(r.path, r.methods, r.name) for r in router.routes if isinstance(r, APIRoute)]


def find_route_index(routes, path_suffix, method="GET"):
    """Find index of a route ending with the given suffix."""
    for i, (path, methods, _) in enumerate(routes):
        if path.endswith(path_suffix) and method in methods:
            return i
    return None


def find_catch_all_index(routes, param_name, method="GET"):
    """Find the index of the first catch-all route with the given param."""
    for i, (path, methods, _) in enumerate(routes):
        if f"{{{param_name}}}" in path and method in methods:
            # Only match if this is the direct /{param} route, not sub-paths like /{param}/download
            path_after_param = path.split(f"{{{param_name}}}")[-1]
            if not path_after_param or path_after_param == "":
                return i
    return None


# --- Poster Routes ---


class TestPosterRouteOrdering:
    """Verify poster routes are not shadowed by /{poster_id}."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.routes = get_routes_for_router("backend.api.posters")

    def _catch_all_idx(self):
        return find_catch_all_index(self.routes, "poster_id")

    def test_catch_all_exists(self):
        assert self._catch_all_idx() is not None

    @pytest.mark.parametrize(
        "route_suffix",
        [
            "/list",
            "/search",
            "/stats",
            "/matched/stats",
            "/unmatched/stats",
            "/gdrive/stats",
            "/preview",
            "/analyze",
            "/browse",
        ],
    )
    def test_named_get_route_before_catch_all(self, route_suffix):
        """Named GET routes must come before GET /{poster_id}."""
        catch_all_idx = self._catch_all_idx()
        route_idx = find_route_index(self.routes, route_suffix, "GET")
        assert route_idx is not None, f"Route ending with {route_suffix} not found"
        assert route_idx < catch_all_idx, (
            f"Route {route_suffix} (index {route_idx}) is after "
            f"/{{poster_id}} (index {catch_all_idx})"
        )

    def test_no_named_get_routes_after_catch_all(self):
        """No named GET routes (without path params) should come after /{poster_id}."""
        catch_all_idx = self._catch_all_idx()
        assert catch_all_idx is not None

        violations = []
        for i, (path, methods, name) in enumerate(self.routes):
            if i > catch_all_idx and "GET" in methods and "{" not in path:
                violations.append(f"  {path} (index {i}, handler={name})")

        assert not violations, (
            f"Named GET routes found after /{{poster_id}} (index {catch_all_idx}):\n"
            + "\n".join(violations)
        )

    @pytest.mark.parametrize(
        "route_suffix",
        ["/gdrive/sync"],
    )
    def test_named_post_route_before_catch_all(self, route_suffix):
        """Named POST routes must come before /{poster_id} routes."""
        catch_all_idx = self._catch_all_idx()
        route_idx = find_route_index(self.routes, route_suffix, "POST")
        assert route_idx is not None, f"Route ending with {route_suffix} not found"
        assert route_idx < catch_all_idx


# --- Media API Routes ---


class TestMediaApiRouteOrdering:
    """Verify media_api routes are not shadowed by /{media_id}."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.routes = get_routes_for_router("backend.api.media_api")

    def test_has_search_route(self):
        assert find_route_index(self.routes, "/search") is not None

    def test_has_stats_route(self):
        assert find_route_index(self.routes, "/stats") is not None

    def test_search_before_media_id(self):
        """If /{media_id} exists, /search must come before it."""
        catch_all_idx = find_catch_all_index(self.routes, "media_id")
        if catch_all_idx is not None:
            search_idx = find_route_index(self.routes, "/search")
            assert search_idx is not None
            assert search_idx < catch_all_idx


# --- Instances Routes ---


class TestInstancesRouteOrdering:
    """Verify instances routes are properly ordered."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.routes = get_routes_for_router("backend.api.instances")

    def test_types_route_exists(self):
        assert find_route_index(self.routes, "/types") is not None

    def test_health_route_exists(self):
        assert find_route_index(self.routes, "/health") is not None

    def test_types_before_instance_id(self):
        """GET /instances/types must come before GET /instances/{instance_id}."""
        catch_all_idx = find_catch_all_index(self.routes, "instance_id")
        if catch_all_idx is not None:
            types_idx = find_route_index(self.routes, "/types")
            assert types_idx is not None
            assert types_idx < catch_all_idx
