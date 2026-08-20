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


class TestBestLineupForcedFormation:
    """best_lineup(formation=...) -- lets a caller force one specific
    formation instead of searching all of them (see its docstring for why:
    one authoritative implementation shared by the auto-search path)."""

    def _full_squad(self, synthetic_pool):
        return opt.build_initial_squad(synthetic_pool)["squad"]

    def test_forced_formation_is_used_exactly(self, synthetic_pool):
        squad = self._full_squad(synthetic_pool)
        forced = {"GK": 1, "DEF": 5, "MID": 2, "FWD": 3}
        result = opt.best_lineup(squad, formation=forced)
        assert result is not None
        assert result["formation"] == forced
        counts = result["starters"]["position"].value_counts().to_dict()
        assert counts == {"DEF": 5, "MID": 2, "FWD": 3, "GK": 1}

    def test_forced_formation_matches_auto_search_when_it_is_the_best_one(self, synthetic_pool):
        """If the globally best formation IS the one forced, results should
        be identical -- confirms the extracted helper didn't change behavior."""
        squad = self._full_squad(synthetic_pool)
        auto = opt.best_lineup(squad)
        forced = opt.best_lineup(squad, formation=auto["formation"])
        assert forced["expected_points"] == auto["expected_points"]
        assert forced["captain"] == auto["captain"]

    def test_invalid_formation_wrong_total_returns_none(self, synthetic_pool):
        squad = self._full_squad(synthetic_pool)
        result = opt.best_lineup(squad, formation={"GK": 1, "DEF": 5, "MID": 5, "FWD": 3})  # sums to 14
        assert result is None

    def test_invalid_formation_outside_limits_returns_none(self, synthetic_pool):
        squad = self._full_squad(synthetic_pool)
        # FWD max is 3 -- 4 is outside FORMATION_LIMITS regardless of total
        result = opt.best_lineup(squad, formation={"GK": 1, "DEF": 3, "MID": 3, "FWD": 4})
        assert result is None

    def test_a_non_optimal_forced_formation_scores_less_or_equal(self, synthetic_pool):
        squad = self._full_squad(synthetic_pool)
        auto = opt.best_lineup(squad)
        # 5-2-3 is always LEGAL but rarely the highest-scoring shape -- if it's
        # not what auto-search picked, it must score <= the auto-search result
        # (auto-search is exhaustive over every valid formation).
        forced = opt.best_lineup(squad, formation={"GK": 1, "DEF": 5, "MID": 2, "FWD": 3})
        assert forced["expected_points"] <= auto["expected_points"] + 1e-9


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


class TestPlanHorizon:
    """plan_horizon() -- multi-gameweek game plan: per-round lineup/captain
    plus greedy free-transfer decisions. See its docstring for why this is
    deliberately greedy round-by-round, not a joint optimization."""

    GAMEWEEKS = [1, 2, 3, 4]

    def _initial_squad_and_candidates(self, synthetic_pool):
        result = opt.build_initial_squad(synthetic_pool)
        squad = result["squad"]
        candidates = synthetic_pool[~synthetic_pool["player_id"].isin(squad["player_id"])]
        return squad, candidates

    def _flat_per_gw(self, synthetic_pool, gameweeks):
        """Every player scores their static xP every gameweek -- a flat
        per-gw frame, good enough when a test doesn't care about week-to-week
        variation."""
        rows = [
            dict(player_id=pid, gw=gw, xP=xp)
            for pid, xp in zip(synthetic_pool["player_id"], synthetic_pool["xP"])
            for gw in gameweeks
        ]
        return pd.DataFrame(rows)

    def test_plan_covers_every_gameweek_with_valid_lineups(self, synthetic_pool):
        squad, candidates = self._initial_squad_and_candidates(synthetic_pool)
        per_gw = self._flat_per_gw(synthetic_pool, self.GAMEWEEKS + [5, 6, 7])  # + lookahead tail
        plan = opt.plan_horizon(squad, candidates, per_gw, self.GAMEWEEKS, bank=0.0,
                                 free_transfers=1, min_gain=999)  # min_gain huge -> never transfer
        assert [step["gameweek"] for step in plan] == self.GAMEWEEKS
        for step in plan:
            counts = step["starters"]["position"].value_counts().to_dict()
            for pos, (lo, hi) in opt.FORMATION_LIMITS.items():
                assert lo <= counts.get(pos, 0) <= hi
            assert step["transfers_in"] == [] and step["transfers_out"] == []
            assert step["hits_taken"] == 0
            assert step["expected_points_after_hits"] == step["expected_points"]

    def test_free_transfers_bank_up_to_cap(self, synthetic_pool):
        """No transfers ever taken (min_gain impossibly high) -> free
        transfers should climb 1 -> 2 -> 3 -> 4, capped at
        MAX_BANKED_FREE_TRANSFERS."""
        squad, candidates = self._initial_squad_and_candidates(synthetic_pool)
        gameweeks = list(range(1, 8))
        per_gw = self._flat_per_gw(synthetic_pool, gameweeks + [8, 9, 10])
        plan = opt.plan_horizon(squad, candidates, per_gw, gameweeks, bank=0.0,
                                 free_transfers=1, min_gain=999)
        after = [step["free_transfers_after"] for step in plan]
        assert after == [min(n, opt.MAX_BANKED_FREE_TRANSFERS) for n in range(2, 2 + len(gameweeks))]

    def test_clear_upgrade_is_transferred_in_and_persists(self, synthetic_pool):
        """A cheap, clearly-superior candidate should get bought in and then
        show up as part of the squad (started or benched) in later rounds."""
        squad, candidates = self._initial_squad_and_candidates(synthetic_pool)
        star_id = 99999
        star_row = pd.DataFrame([dict(
            player_id=star_id, name="Star_DEF", position="DEF",
            team_id=hash("Star FC") % 1000, team="Star FC", price=4.0, xP=0.0,
        )])
        candidates = pd.concat([candidates, star_row], ignore_index=True)

        gameweeks = [1, 2, 3]
        per_gw = self._flat_per_gw(synthetic_pool, gameweeks + [4, 5, 6])
        # Star player massively outscores everyone from gw1 onward.
        star_rows = pd.DataFrame([dict(player_id=star_id, gw=gw, xP=20.0) for gw in gameweeks + [4, 5, 6]])
        per_gw = pd.concat([per_gw, star_rows], ignore_index=True)

        plan = opt.plan_horizon(squad, candidates, per_gw, gameweeks, bank=10.0,
                                 free_transfers=1, min_gain=2.0)
        assert star_id in plan[0]["transfers_in"]
        assert "Star_DEF" in plan[0]["transfers_in_names"]
        # Confirm it sticks around: present in gw3's squad (started or benched)
        gw3_ids = set(plan[2]["starters"]["player_id"]) | set(plan[2]["bench"]["player_id"])
        assert star_id in gw3_ids
        # Only ever spends free transfers actually available (1/round here)
        assert all(len(step["transfers_in"]) <= 1 for step in plan)

    def test_min_hold_weeks_prevents_immediate_transfer_reversal(self, synthetic_pool):
        """A player bought this plan for one big week shouldn't be sold
        again the very next round just because the lookahead window shifted
        and someone else briefly looks better -- see min_hold_weeks' own
        docstring for the exact thrash this guards against."""
        squad, candidates = self._initial_squad_and_candidates(synthetic_pool)
        star_a_id, star_b_id = 77001, 77002
        star_rows = pd.DataFrame([
            dict(player_id=star_a_id, name="Star_A", position="DEF",
                 team_id=hash("Star A FC") % 1000, team="Star A FC", price=4.0, xP=0.0),
            dict(player_id=star_b_id, name="Star_B", position="DEF",
                 team_id=hash("Star B FC") % 1000, team="Star B FC", price=4.0, xP=0.0),
        ])
        candidates = pd.concat([candidates, star_rows], ignore_index=True)

        gameweeks = [1, 2, 3]
        per_gw = self._flat_per_gw(synthetic_pool, gameweeks + [4, 5, 6])
        # Star_A has ONE huge week (gw1) then goes quiet; Star_B has its one
        # huge week the round right after (gw2) -- exactly the setup that
        # would make "sell Star_A, buy Star_B" look like a great idea at gw2
        # if nothing were protecting a just-bought player.
        extra = pd.DataFrame(
            [dict(player_id=star_a_id, gw=gw, xP=20.0 if gw == 1 else 0.0) for gw in gameweeks + [4, 5, 6]]
            + [dict(player_id=star_b_id, gw=gw, xP=20.0 if gw == 2 else 0.0) for gw in gameweeks + [4, 5, 6]]
        )
        per_gw = pd.concat([per_gw, extra], ignore_index=True)

        plan = opt.plan_horizon(squad, candidates, per_gw, gameweeks, bank=20.0,
                                 free_transfers=1, min_gain=2.0, min_hold_weeks=2)

        assert star_a_id in plan[0]["transfers_in"]  # bought at gw1 for its one big week
        assert star_a_id not in plan[1]["transfers_out"]  # NOT immediately sold back at gw2

    def test_hits_not_taken_by_default_even_when_profitable(self, synthetic_pool):
        """A second, only-slightly-worse star (still a big enough gain to be
        worth a -4 hit) should NOT be bought when allow_hits is left at its
        default False -- only the single free transfer is used."""
        squad, candidates = self._initial_squad_and_candidates(synthetic_pool)
        star_ids = [88888, 88889]
        star_rows = pd.DataFrame([
            dict(player_id=sid, name=f"Star_{i}", position="DEF",
                 team_id=hash(f"Star{i} FC") % 1000, team=f"Star{i} FC", price=4.0, xP=0.0)
            for i, sid in enumerate(star_ids)
        ])
        candidates = pd.concat([candidates, star_rows], ignore_index=True)

        gameweeks = [1, 2]
        per_gw = self._flat_per_gw(synthetic_pool, gameweeks + [3, 4, 5])
        # Both stars outscore everything, comfortably enough to justify a hit (gain > min_gain + 4)
        per_gw = pd.concat([per_gw, pd.DataFrame([
            dict(player_id=sid, gw=gw, xP=20.0) for sid in star_ids for gw in gameweeks + [3, 4, 5]
        ])], ignore_index=True)

        plan = opt.plan_horizon(squad, candidates, per_gw, gameweeks, bank=10.0,
                                 free_transfers=1, min_gain=2.0, allow_hits=False)
        assert len(plan[0]["transfers_in"]) == 1  # only the free one
        assert plan[0]["hits_taken"] == 0
        assert plan[0]["expected_points_after_hits"] == plan[0]["expected_points"]

    def test_hits_taken_when_allowed_and_worth_it(self, synthetic_pool):
        """Same scenario, but with allow_hits=True -- the second star is
        worth buying too, taking a real -4 hit, reflected in
        expected_points_after_hits but NOT in the raw expected_points."""
        squad, candidates = self._initial_squad_and_candidates(synthetic_pool)
        star_ids = [88888, 88889]
        star_rows = pd.DataFrame([
            dict(player_id=sid, name=f"Star_{i}", position="DEF",
                 team_id=hash(f"Star{i} FC") % 1000, team=f"Star{i} FC", price=4.0, xP=0.0)
            for i, sid in enumerate(star_ids)
        ])
        candidates = pd.concat([candidates, star_rows], ignore_index=True)

        gameweeks = [1, 2]
        per_gw = self._flat_per_gw(synthetic_pool, gameweeks + [3, 4, 5])
        per_gw = pd.concat([per_gw, pd.DataFrame([
            dict(player_id=sid, gw=gw, xP=20.0) for sid in star_ids for gw in gameweeks + [3, 4, 5]
        ])], ignore_index=True)

        plan = opt.plan_horizon(squad, candidates, per_gw, gameweeks, bank=10.0,
                                 free_transfers=1, min_gain=2.0, allow_hits=True, hit_cost=4.0)
        assert len(plan[0]["transfers_in"]) == 2
        assert plan[0]["hits_taken"] == 1
        assert plan[0]["expected_points_after_hits"] == pytest.approx(plan[0]["expected_points"] - 4.0)
        assert plan[0]["expected_points_with_captain_after_hits"] == pytest.approx(
            plan[0]["expected_points_with_captain"] - 4.0
        )

    def test_hits_capped_at_max_hits_per_gw(self, synthetic_pool):
        """Even with several profitable-looking upgrades available, hits in
        one round never exceed max_hits_per_gw."""
        squad, candidates = self._initial_squad_and_candidates(synthetic_pool)
        star_ids = list(range(90000, 90005))  # 5 candidates, way more than max_hits_per_gw
        star_rows = pd.DataFrame([
            dict(player_id=sid, name=f"Star_{i}", position="DEF",
                 team_id=hash(f"Star{i} Utd") % 1000, team=f"Star{i} Utd", price=4.0, xP=0.0)
            for i, sid in enumerate(star_ids)
        ])
        candidates = pd.concat([candidates, star_rows], ignore_index=True)

        gameweeks = [1]
        per_gw = self._flat_per_gw(synthetic_pool, gameweeks + [2, 3, 4])
        per_gw = pd.concat([per_gw, pd.DataFrame([
            dict(player_id=sid, gw=gw, xP=20.0) for sid in star_ids for gw in gameweeks + [2, 3, 4]
        ])], ignore_index=True)

        plan = opt.plan_horizon(squad, candidates, per_gw, gameweeks, bank=50.0,
                                 free_transfers=1, min_gain=2.0, allow_hits=True,
                                 hit_cost=4.0, max_hits_per_gw=2)
        assert plan[0]["hits_taken"] <= 2
        assert len(plan[0]["transfers_in"]) <= 3  # 1 free + up to 2 hits
