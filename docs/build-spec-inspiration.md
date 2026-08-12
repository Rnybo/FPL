# Inspiration from BUILD_SPEC.md — what we're taking and why

`BUILD_SPEC.md` is this Claude Project's attached file: a full spec for a similarly-scoped
Streamlit FPL app ("FPL Scout"). Not a dependency, not code we import — read for design ideas,
same way vaastav's repo was used for the historical-data shape (see `historical-data-source.md`).

## What changes our roadmap

### Layer 6 (optimizer) — adapt their pattern, don't build a MILP from scratch
Their `optimise.py` (`best_lineup`, `suggest_transfers`) exploits a real structural fact about
FPL: players are interchangeable *within* a position for squad-selection purposes, so a greedy
per-formation selection is **exact**, not an approximation — no need for `highspy`/PuLP. Their
own Section 11 says this explicitly. Simpler, faster, and correct for this specific problem
shape. We should build our optimizer this way, not the MILP approach floated earlier in
`model-architecture.md` — that doc will be updated to reflect this.

### VORP + tiers (their Section 10) — worth adding once xP is stable
`assign_tiers` (gap-based clustering, scale-invariant) and `flex_replacement_values` (formation-
minimums-first, then best-remaining-points for flex seats) are clean, well-reasoned designs.
Useful for both classic squad-building and the Draft-mode use case if we ever build that.

### Captaincy simulation (their Section 8) — a good complement to point-estimate xP
`captain_distribution`: Monte Carlo using the same Poisson counting stats we already compute,
giving floor/ceiling/blank%/haul% per player, not just a mean. We already have every input this
needs (our own λ's from `combine_xp.py`) — this is mostly a sampling wrapper around what exists,
not a new modeling layer.

### Differential value + return_pct (their Section 17 glossary) — cheap additions later
`differential = xp_total × (1 − ownership/100)`, `return_pct` = chance of any return next GW.
Trivial once xP + ownership data exist. Not urgent, but low-effort when we get there.

### What we're NOT adopting
- Their Streamlit UI/pages structure — out of scope for now, this project isn't UI-focused yet.
- Their live squad-loading (`entry/{id}/picks`) — not needed until we build a "manage my actual
  team" feature, which isn't the current goal (projection quality is).
- Their offline-sample-data testing approach — we're working against real historical data
  directly, don't need a synthetic fixture set.

## Updated Layer 6 plan
Replaces the MILP section in `docs/model-architecture.md`:
1. Enumerate valid formations from `FORMATION_LIMITS` (see `claude.md`)
2. Per formation, greedily take top-xP players per position slot (exact, given interchangeability)
3. Captain = top scorer in the chosen XI, vice = second
4. `suggest_transfers`: for each squad member, find the best affordable upgrade at their
   position (respecting bank + 3-per-club), keep the best gain per outgoing player
5. Layer this on top of `combine_xp.py`'s output once Layer 3 live-status integration is done
   (see the multi-gameweek forecasting note for why xP needs to exist for FUTURE fixtures too,
   not just backtested historical ones, before an optimizer is useful)
