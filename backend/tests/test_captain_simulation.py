"""
Pure-logic tests for captain_simulation.py -- see BUILD_SPEC.md's testing
philosophy: synthetic data for pure-logic units, real DB reserved for
integration. No existing coverage of this module before this session's
Haaland-ceiling bug fix -- added here.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from captain_simulation import (
    _scaled_bonus, _blend_start_rate, simulate_player_points, summarize,
    BLEND_WEIGHT_REAL_START_RATE,
)


class TestScaledBonus:
    """Captaincy's whole ceiling depends on this -- see module docstring's
    "Bonus:" section. Fixes a real bug: previously a hat-trick sample got
    the exact same bonus as a blank."""

    def test_bonus_scales_up_with_bigger_performance(self):
        base_pts = np.array([0.0, 5.0, 20.0])
        result = _scaled_bonus(base_pts, expected_base_pts=5.0, expected_bonus=1.0)
        assert result[0] < result[1] < result[2]

    def test_bonus_equals_expected_bonus_at_exactly_average_performance(self):
        result = _scaled_bonus(np.array([5.0]), expected_base_pts=5.0, expected_bonus=1.5)
        assert result[0] == pytest.approx(1.5)

    def test_bonus_clipped_to_real_max_of_three(self):
        result = _scaled_bonus(np.array([1000.0]), expected_base_pts=1.0, expected_bonus=1.0)
        assert result[0] == 3.0

    def test_bonus_clipped_to_real_min_of_zero(self):
        result = _scaled_bonus(np.array([-5.0]), expected_base_pts=1.0, expected_bonus=1.0)
        assert result[0] == 0.0

    def test_zero_performance_gives_zero_bonus(self):
        result = _scaled_bonus(np.array([0.0]), expected_base_pts=5.0, expected_bonus=2.0)
        assert result[0] == 0.0

    def test_player_not_expected_to_contribute_at_all_keeps_flat_average_on_a_blank(self):
        # expected_base_pts ~ 0 means the model itself doesn't expect this
        # player to score/assist/CS/defcon -- a genuine blank keeps the flat
        # average rather than dividing by ~zero.
        result = _scaled_bonus(np.array([0.0]), expected_base_pts=0.0, expected_bonus=0.5)
        assert result[0] == pytest.approx(0.5)

    def test_player_not_expected_to_contribute_but_gets_a_surprise_contribution(self):
        result = _scaled_bonus(np.array([3.0]), expected_base_pts=0.0, expected_bonus=0.5)
        assert result[0] == 1.5  # 0.5 * 3.0 (the "surprise" multiplier)


class TestBlendStartRate:
    """Real last-season start% gets a MINORITY blend weight against the
    model's own p_played -- see BLEND_WEIGHT_REAL_START_RATE's docstring."""

    def test_blends_toward_real_rate_when_available(self):
        p_played, _ = _blend_start_rate(
            pd.Series([0.9]), pd.Series([0.8]), pd.Series([0.5])
        )
        expected = BLEND_WEIGHT_REAL_START_RATE * 0.5 + (1 - BLEND_WEIGHT_REAL_START_RATE) * 0.9
        assert p_played[0] == pytest.approx(expected)
        assert p_played[0] < 0.9  # pulled toward the (lower) real rate

    def test_falls_back_to_model_when_no_real_data(self):
        p_played, p_60plus = _blend_start_rate(
            pd.Series([0.7]), pd.Series([0.6]), pd.Series([np.nan])
        )
        assert p_played[0] == 0.7
        assert p_60plus[0] == 0.6

    def test_p_60plus_never_exceeds_p_played_even_after_a_big_blend_swing(self):
        p_played, p_60plus = _blend_start_rate(
            pd.Series([0.3]), pd.Series([0.25]), pd.Series([0.95])
        )
        assert p_60plus[0] <= p_played[0]

    def test_p_60plus_ratio_preserved_when_no_blend_occurs(self):
        # No real data -- nothing should change, including the p_60plus/p_played ratio.
        p_played, p_60plus = _blend_start_rate(
            pd.Series([0.8]), pd.Series([0.6]), pd.Series([np.nan])
        )
        assert p_60plus[0] / p_played[0] == pytest.approx(0.75)


class TestSimulatePlayerPoints:
    def _row(self, **overrides):
        base = dict(
            position="FWD", lambda_goal=0.6, lambda_assist=0.2, p_clean_sheet=0.0,
            p_defcon=0.0, lambda_saves=0.0, expected_bonus=0.6, minor_pts_fixed=0.0,
            p_played=0.9, p_60plus=0.8,
        )
        base.update(overrides)
        return pd.DataFrame([base])

    def test_zero_p_played_gives_all_zero_samples(self):
        samples = simulate_player_points(self._row(p_played=0.0, p_60plus=0.0), n_samples=500, seed=0)
        assert (samples == 0).all()

    def test_certain_appearance_never_returns_zero(self):
        samples = simulate_player_points(self._row(p_played=1.0, p_60plus=1.0), n_samples=500, seed=0)
        assert (samples > 0).all()  # at minimum, the 2 appearance points

    def test_higher_goal_rate_increases_mean_points(self):
        low = simulate_player_points(self._row(lambda_goal=0.1), n_samples=20000, seed=0)
        high = simulate_player_points(self._row(lambda_goal=1.0), n_samples=20000, seed=0)
        assert high.mean() > low.mean()

    def test_double_gameweek_sums_across_both_fixtures(self):
        one_fixture = simulate_player_points(self._row(), n_samples=20000, seed=0)
        two_fixtures = pd.concat([self._row(), self._row()], ignore_index=True)
        double = simulate_player_points(two_fixtures, n_samples=20000, seed=0)
        assert double.mean() > one_fixture.mean() * 1.5  # meaningfully more, not identical

    def test_summarize_shape(self):
        samples = simulate_player_points(self._row(), n_samples=1000, seed=0)
        stats = summarize(samples)
        assert set(stats.keys()) == {"mean", "p10", "p90", "p_haul", "p_blank"}
        assert stats["p10"] <= stats["mean"] <= stats["p90"]
        assert 0 <= stats["p_haul"] <= 1
        assert 0 <= stats["p_blank"] <= 1
