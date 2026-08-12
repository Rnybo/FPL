"""
Synthetic fixtures for backend tests (see BUILD_SPEC.md's own testing
philosophy: pure-logic tests use synthetic data, not the real cache DB --
that's reserved for integration tests in test_api.py).
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))


@pytest.fixture
def synthetic_pool():
    """30 players across 11 distinct clubs -- enough that max-3-per-club
    (with 15 needed) is comfortably satisfiable, while still deliberately
    over-supplying Rich FC's defenders (5, only 3 allowed) so that specific
    constraint is genuinely tested, not just declared and never hit. GK
    candidates are each in their OWN single-purpose club so that test is
    fully isolated from cross-position club-budget competition."""
    rows = []
    pid = 1

    def add(position, team, price, xp, n=1):
        nonlocal pid
        for _ in range(n):
            rows.append(dict(player_id=pid, name=f"{position}_{pid}", position=position,
                              team_id=hash(team) % 1000, team=team, price=price, xP=xp))
            pid += 1

    # GK: 4 total, each its own club -- isolates this sub-problem cleanly
    add("GK", "GKClub_A", 4.0, 3.0)
    add("GK", "GKClub_B", 4.5, 3.5)
    add("GK", "GKClub_C", 5.0, 4.5)
    add("GK", "GKClub_D", 5.5, 5.0)

    # DEF: 10 total. Rich FC deliberately has 5 (exceeds max_per_club=3).
    add("DEF", "Rich FC", 6.0, 6.0)
    add("DEF", "Rich FC", 5.8, 5.8)
    add("DEF", "Rich FC", 5.5, 5.5)
    add("DEF", "Rich FC", 5.2, 5.2)
    add("DEF", "Rich FC", 5.0, 5.0)
    add("DEF", "Club B", 4.0, 3.0, n=3)
    add("DEF", "Club C", 4.5, 3.8, n=2)

    # MID: 10 total
    add("MID", "Club D", 8.0, 7.0, n=2)
    add("MID", "Club E", 6.5, 5.5, n=4)
    add("MID", "Club F", 5.0, 4.0, n=4)

    # FWD: 6 total
    add("FWD", "Rich FC", 9.0, 7.5)
    add("FWD", "Club F", 7.0, 5.5, n=2)
    add("FWD", "Club G", 5.5, 4.0, n=3)

    return pd.DataFrame(rows)
