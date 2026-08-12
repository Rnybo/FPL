"""
Pure-logic tests for squad.py's own helpers (not covered by test_optimise.py,
which is optimise.py's own solver logic, or test_api.py, which is real-DB
integration). See BUILD_SPEC.md's testing philosophy: synthetic data for
pure-logic units.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.routers.squad import _parse_formation, _captain_ceiling_from_per_gw, CAPTAIN_CEILING_WEIGHT
from fastapi import HTTPException


class TestParseFormation:
    def test_parses_standard_shorthand(self):
        assert _parse_formation("4-4-2") == {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2}

    def test_parses_extremes(self):
        assert _parse_formation("5-2-3") == {"GK": 1, "DEF": 5, "MID": 2, "FWD": 3}
        assert _parse_formation("3-5-2") == {"GK": 1, "DEF": 3, "MID": 5, "FWD": 2}

    def test_rejects_wrong_number_of_parts(self):
        with pytest.raises(HTTPException):
            _parse_formation("4-4")

    def test_rejects_non_numeric_parts(self):
        with pytest.raises(HTTPException):
            _parse_formation("four-four-two")


class TestCaptainCeilingBonus:
    """Captaincy doubles whichever squad member scores most in a given
    gameweek -- so a player with one genuine standout week is worth more to
    captaincy planning than a flat player with the same TOTAL but no single
    week that stands out. This is the whole point of CAPTAIN_CEILING_WEIGHT
    (see its own docstring in squad.py for why it's a documented
    approximation, not an exact per-week optimization)."""

    def test_spiky_player_scores_higher_than_flat_player_with_same_total(self):
        pool = pd.DataFrame([
            {"player_id": 1, "selection_score": 10.0},  # flat: 2+2+2+2+2
            {"player_id": 2, "selection_score": 10.0},  # spiky: 8+0.5+0.5+0.5+0.5
        ])
        per_gw = pd.DataFrame(
            [{"player_id": 1, "gw": gw, "xP": 2.0} for gw in range(1, 6)]
            + [{"player_id": 2, "gw": 1, "xP": 8.0}]
            + [{"player_id": 2, "gw": gw, "xP": 0.5} for gw in range(2, 6)]
        )

        result = _captain_ceiling_from_per_gw(pool, per_gw)
        flat_score = result.loc[result["player_id"] == 1, "selection_score"].iloc[0]
        spiky_score = result.loc[result["player_id"] == 2, "selection_score"].iloc[0]

        assert spiky_score > flat_score
        assert flat_score == pytest.approx(10.0 + CAPTAIN_CEILING_WEIGHT * 2.0)
        assert spiky_score == pytest.approx(10.0 + CAPTAIN_CEILING_WEIGHT * 8.0)

    def test_empty_per_gw_leaves_pool_unchanged(self):
        pool = pd.DataFrame([{"player_id": 1, "selection_score": 5.0}])
        result = _captain_ceiling_from_per_gw(pool, pd.DataFrame(columns=["player_id", "gw", "xP"]))
        assert result.loc[0, "selection_score"] == 5.0

    def test_player_missing_from_per_gw_gets_zero_bonus_not_a_crash(self):
        pool = pd.DataFrame([{"player_id": 1, "selection_score": 5.0}, {"player_id": 999, "selection_score": 3.0}])
        per_gw = pd.DataFrame([{"player_id": 1, "gw": 1, "xP": 4.0}])  # nothing for player 999
        result = _captain_ceiling_from_per_gw(pool, per_gw)
        assert result.loc[result["player_id"] == 999, "selection_score"].iloc[0] == 3.0
