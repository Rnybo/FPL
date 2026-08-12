"""
Tests for optimise.py -- see module docstring there for why best_lineup is
exact (no solver needed) but build_initial_squad genuinely needs the ILP.
"""
import pandas as pd
import pytest

import optimise as opt


class TestValidFormations:
    def test_all_sum_to_eleven(self):
        for f in opt.valid_formations():
            assert sum(f.values()) == 11

    def test_gk_always_one(self):
        for f in opt.valid_formations():
            assert f["GK"] == 1

    def test_respects_formation_limits(self):
        for f in opt.valid_formations():
            for pos, (lo, hi) in opt.FORMATION_LIMITS.items():
                assert lo <= f[pos] <= hi

    def test_known_formation_count(self):
        # DEF 3-5, MID 2-5, FWD 1-3, summing to 10 (GK fixed at 1) -- enumerate by hand
        expected = sum(
            1
            for d in range(3, 6) for m in range(2, 6) for fw in range(1, 4)
            if d + m + fw == 10
        )
        assert len(opt.valid_formations()) == expected


class TestBuildInitialSquad:
    def test_respects_squad_limits(self, synthetic_pool):
        result = opt.build_initial_squad(synthetic_pool)
        assert result["status"] == "Optimal"
        counts = result["squad"]["position"].value_counts().to_dict()
        assert counts == opt.SQUAD_LIMITS

    def test_respects_budget(self, synthetic_pool):
        result = opt.build_initial_squad(synthetic_pool, budget=100.0)
        assert result["squad"]["price"].sum() <= 100.0

    def test_club_limit_actually_bites(self, synthetic_pool):
        """The fixture has 5 strong Rich FC defenders -- verify the optimizer
        doesn't just pick all 5 (it can't: max 3 per club), i.e. the
        constraint is actually enforced, not just declared."""
        result = opt.build_initial_squad(synthetic_pool)
        club_counts = result["squad"]["team"].value_counts()
        assert club_counts.get("Rich FC", 0) <= opt.MAX_PER_CLUB

    def test_picks_higher_value_over_lower(self, synthetic_pool):
        """Sanity check the objective is actually being maximized: GK price
        differences are small relative to total budget, so the two highest-xP
        GKs (GKClub_D xP5.0, GKClub_C xP4.5) should be chosen over the
        weaker options -- not just "any 2 that fit"."""
        result = opt.build_initial_squad(synthetic_pool)
        gks = result["squad"][result["squad"]["position"] == "GK"]
        assert set(gks["xP"]) == {5.0, 4.5}

    def test_lock_forces_inclusion(self, synthetic_pool):
        weak_gk_id = synthetic_pool[
            (synthetic_pool["position"] == "GK") & (synthetic_pool["team"] == "GKClub_A")
        ]["player_id"].iloc[0]
        result = opt.build_initial_squad(synthetic_pool, locked_player_ids=[weak_gk_id])
        assert result["status"] == "Optimal"
        assert weak_gk_id in result["squad"]["player_id"].values

    def test_lock_still_respects_budget_and_limits(self, synthetic_pool):
        weak_gk_id = synthetic_pool[
            (synthetic_pool["position"] == "GK") & (synthetic_pool["team"] == "GKClub_A")
        ]["player_id"].iloc[0]
        result = opt.build_initial_squad(synthetic_pool, locked_player_ids=[weak_gk_id])
        assert result["squad"]["price"].sum() <= opt.BUDGET
        assert result["squad"]["position"].value_counts().to_dict() == opt.SQUAD_LIMITS

    def test_unknown_locked_player_id_reported(self, synthetic_pool):
        result = opt.build_initial_squad(synthetic_pool, locked_player_ids=[999999])
        assert result["status"] == "PlayerNotFound"
        assert result["squad"] is None
        assert 999999 in result["missing_player_ids"]

    def test_too_many_locks_same_club_infeasible(self, synthetic_pool):
        """Locking 4 players from Rich FC violates max-3-per-club -- should
        report infeasible, not silently drop the constraint or crash."""
        rich_ids = synthetic_pool[synthetic_pool["team"] == "Rich FC"]["player_id"].head(4).tolist()
        result = opt.build_initial_squad(synthetic_pool, locked_player_ids=rich_ids)
        assert result["status"] != "Optimal"
        assert result["squad"] is None


class TestBuildOptimalSquadAndLineup:
    """The joint optimizer -- see its docstring for why the OLD two-stage
    approach (build_initial_squad then best_lineup) had a real objective bug:
    it valued all 15 squad players equally when only 11 score points."""

    def test_respects_squad_and_formation_limits(self, synthetic_pool):
        result = opt.build_optimal_squad_and_lineup(synthetic_pool)
        assert result["status"] == "Optimal"
        assert result["squad"]["position"].value_counts().to_dict() == opt.SQUAD_LIMITS
        starters = result["lineup"]["starters"]
        assert len(starters) == opt.STARTING_XI
        for pos, (lo, hi) in opt.FORMATION_LIMITS.items():
            n = (starters["position"] == pos).sum()
            assert lo <= n <= hi

    def test_respects_budget_and_club_limit(self, synthetic_pool):
        result = opt.build_optimal_squad_and_lineup(synthetic_pool)
        assert result["squad"]["price"].sum() <= opt.BUDGET
        club_counts = result["squad"]["team"].value_counts()
        assert club_counts.get("Rich FC", 0) <= opt.MAX_PER_CLUB

    def test_starting_xi_xp_beats_the_old_two_stage_approach(self, synthetic_pool):
        """The actual point of this fix: given the SAME budget, the joint
        optimizer's starting XI should score at least as much as picking 15
        blind to who starts, then post-hoc choosing the best 11 -- verified
        directly against real GW1-5 data separately (see docs/GOTCHAS.md,
        +2.66 xP improvement there); here confirmed >= holds structurally."""
        old_result = opt.build_initial_squad(synthetic_pool)
        old_lineup = opt.best_lineup(old_result["squad"])
        new_result = opt.build_optimal_squad_and_lineup(synthetic_pool)
        assert new_result["lineup"]["expected_points"] >= old_lineup["expected_points"] - 1e-6

    def test_locked_player_stays_in_squad_but_starting_status_is_free(self, synthetic_pool):
        """Locking pins SQUAD membership, not STARTING status -- the
        optimizer should still be free to bench a locked player if that's
        better for the weighted objective."""
        weak_gk_id = synthetic_pool[
            (synthetic_pool["position"] == "GK") & (synthetic_pool["team"] == "GKClub_A")
        ]["player_id"].iloc[0]
        result = opt.build_optimal_squad_and_lineup(synthetic_pool, locked_player_ids=[weak_gk_id])
        assert result["status"] == "Optimal"
        assert weak_gk_id in result["squad"]["player_id"].values
        # the weakest GK (xP=3.0) should lose the starting slot to a stronger one if unlocked
        starter_ids = result["lineup"]["starters"]["player_id"].values
        assert weak_gk_id not in starter_ids or len(
            synthetic_pool[synthetic_pool["position"] == "GK"]
        ) == 1  # only meaningful if there was a better alternative available

    def test_unknown_locked_player_id_reported(self, synthetic_pool):
        result = opt.build_optimal_squad_and_lineup(synthetic_pool, locked_player_ids=[999999])
        assert result["status"] == "PlayerNotFound"
        assert result["squad"] is None
