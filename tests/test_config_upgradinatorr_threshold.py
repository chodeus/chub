"""UpgradinatorrInstance.season_monitored_threshold is a 0–100 percentage."""

import pytest

from backend.util.config import UpgradinatorrInstance


@pytest.mark.parametrize(
    "given, expected",
    [(150, 100.0), (-5, 0.0), (50, 50), (0.5, 0.5), (None, None), (float("nan"), None)],
)
def test_threshold_is_clamped_not_rejected(given, expected):
    instance = UpgradinatorrInstance(
        instance="sonarr", season_monitored_threshold=given
    )
    assert instance.season_monitored_threshold == expected
