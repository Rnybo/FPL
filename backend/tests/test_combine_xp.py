"""
Tests for combine_xp.py's math helpers -- verified against hand-computable
values, not just "it runs". These are the functions the whole xP pipeline's
correctness depends on, so they're worth pinning down precisely.
"""
import numpy as np
import pandas as pd
import pytest
from scipy.stats import poisson

import combine_xp as cx


class TestExpectedFloorDivK:
    def test_zero_lambda_gives_zero(self):
        result = cx.expected_floor_div_k(np.array([1e-9]), k=2)
        assert result[0] == pytest.approx(0.0, abs=1e-6)

    def test_matches_hand_computed_value(self):
        """For lambda=2, k=2: E[floor(X/2)] where X~Poisson(2).
        Compute directly via the pmf definition, independent of the
        function's own implementation, to catch a shared-bug scenario."""
        lam = 2.0
        ks = np.arange(30)
        expected = sum((k // 2) * poisson.pmf(k, lam) for k in ks)
        result = cx.expected_floor_div_k(np.array([lam]), k=2, cap=29)
        assert result[0] == pytest.approx(expected, rel=1e-4)

    def test_monotonic_in_lambda(self):
        """Higher expected goals conceded should never produce a LOWER
        expected points deduction."""
        lams = np.array([0.5, 1.0, 2.0, 3.0])
        result = cx.expected_floor_div_k(lams, k=2)
        assert np.all(np.diff(result) >= 0)


class TestCleanSheetProb:
    """This function was rewritten for performance (see docs/GOTCHAS.md --
    77s -> vectorized) and verified against the original row-by-row version
    at the time, but that verification was a throwaway script, not a
    permanent test. Recreating the same check here so it can't silently
    regress."""

    def _old_row_by_row(self, was_home, lh_for, la_against, rho):
        if was_home:
            lh, la = lh_for, la_against
            p00 = poisson.pmf(0, lh) * poisson.pmf(0, la) * (1 - lh * la * rho)
            p10 = poisson.pmf(1, lh) * poisson.pmf(0, la) * (1 + la * rho)
            p_rest = sum(poisson.pmf(x, lh) * poisson.pmf(0, la) for x in range(2, 12))
        else:
            lh, la = la_against, lh_for
            p00 = poisson.pmf(0, lh) * poisson.pmf(0, la) * (1 - lh * la * rho)
            p01 = poisson.pmf(0, lh) * poisson.pmf(1, la) * (1 + lh * rho)
            p_rest = sum(poisson.pmf(0, lh) * poisson.pmf(y, la) for y in range(2, 12))
            p00, p10 = p00, p01
        return p00 + p10 + p_rest

    def test_matches_original_implementation(self):
        rho = -0.08
        rng = np.random.default_rng(42)
        for _ in range(200):
            was_home = bool(rng.integers(0, 2))
            lh_for = rng.uniform(0.3, 3.0)
            la_against = rng.uniform(0.3, 3.0)
            expected = self._old_row_by_row(was_home, lh_for, la_against, rho)

            df = pd.DataFrame({
                "was_home": [was_home],
                "team_lambda_for": [lh_for],
                "team_lambda_against": [la_against],
            })
            result = cx.add_clean_sheet_prob(df, rho)
            assert result["p_clean_sheet"].iloc[0] == pytest.approx(expected, abs=1e-9)

    def test_probability_in_valid_range(self):
        df = pd.DataFrame({
            "was_home": [True, False, True],
            "team_lambda_for": [1.5, 0.8, 2.5],
            "team_lambda_against": [0.9, 1.8, 0.5],
        })
        result = cx.add_clean_sheet_prob(df, rho=-0.1)
        assert result["p_clean_sheet"].between(0, 1).all()
