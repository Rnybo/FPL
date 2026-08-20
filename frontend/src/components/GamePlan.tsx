// Shared presentational components for the multi-gameweek game plan (Game
// Plan on My Team, Drejebog on Squad Builder) -- both wrap optimise.py's
// plan_horizon via different endpoints (team.py vs squad.py), but the
// rendering is identical, so it lives here once rather than duplicated.
import { useState } from 'react'
import { ChevronDown, ChevronRight, ArrowRight, ArrowUpDown, ArrowUp, ArrowDown, Zap, Wallet, RefreshCw } from 'lucide-react'
import type { TeamPlanStep } from '../api/types'

const POSITION_ORDER = ['GK', 'DEF', 'MID', 'FWD'] as const

function formationLabel(formation: Record<string, number>): string {
  return ['DEF', 'MID', 'FWD'].map((pos) => formation[pos] ?? 0).join('-')
}

// Everything a person would need to spot at a glance what changed vs the
// PREVIOUS planned gameweek -- not just transfers (already tracked on the
// step itself), but lineup reshuffles that happen with no transfer at all:
// a player dropping to the bench because their fixture got tougher, the
// bench sub-priority order reshuffling, or the captain armband moving.
// Players who were just transferred IN this round are deliberately excluded
// from movedIntoXI/movedToBench -- they're not "in the squad both rounds",
// and are already called out via step.transfers_in elsewhere.
interface StepDiff {
  movedIntoXI: Set<number>
  movedToBench: Set<number>
  benchOrderChanges: Map<number, number> // player_id -> previous bench slot index (0-based)
  formationChanged: boolean
  prevFormationLabel: string
  captainChanged: boolean
  prevCaptain: string
  viceChanged: boolean
}

function diffSteps(prev: TeamPlanStep | undefined, curr: TeamPlanStep): StepDiff | null {
  if (!prev) return null
  const prevStarterSet = new Set(prev.starter_ids)
  const prevBenchSet = new Set(prev.bench_ids)
  const transferredInSet = new Set(curr.transfers_in)

  const movedIntoXI = new Set<number>()
  curr.starter_ids.forEach((id) => {
    if (!transferredInSet.has(id) && prevBenchSet.has(id)) movedIntoXI.add(id)
  })

  const movedToBench = new Set<number>()
  curr.bench_ids.forEach((id) => {
    if (!transferredInSet.has(id) && prevStarterSet.has(id)) movedToBench.add(id)
  })

  const benchOrderChanges = new Map<number, number>()
  curr.bench_ids.forEach((id, idx) => {
    const prevIdx = prev.bench_ids.indexOf(id)
    if (prevIdx !== -1 && prevIdx !== idx && !movedToBench.has(id)) benchOrderChanges.set(id, prevIdx)
  })

  return {
    movedIntoXI, movedToBench, benchOrderChanges,
    formationChanged: formationLabel(prev.formation) !== formationLabel(curr.formation),
    prevFormationLabel: formationLabel(prev.formation),
    captainChanged: prev.captain !== curr.captain,
    prevCaptain: prev.captain,
    viceChanged: prev.vice_captain !== curr.vice_captain,
  }
}

// Presets, not a raw number input -- "minimum xP gain to justify a
// transfer" isn't a number most people have an intuition for, but
// "conservative/balanced/aggressive" is. See squad.py/team.py's min_gain
// query param.
export const MIN_GAIN_PRESETS = [
  { label: 'Conservative', value: 2.0, hint: 'Only clear, obvious upgrades' },
  { label: 'Balanced', value: 1.0, hint: 'Default middle ground' },
  { label: 'Aggressive', value: 0.25, hint: 'Suggests marginal upgrades too' },
] as const

export function GamePlanControls({
  horizon, onHorizonChange, freeTransfersInput, onFreeTransfersInputChange, freeTransfers,
  allowHits, onAllowHitsChange, minGain, onMinGainChange, isFetching, isLoading, horizonOptions = [3, 5, 8],
}: {
  horizon: number
  onHorizonChange: (n: number) => void
  freeTransfersInput: string
  onFreeTransfersInputChange: (v: string) => void
  freeTransfers: number
  allowHits: boolean
  onAllowHitsChange: (v: boolean) => void
  minGain: number
  onMinGainChange: (v: number) => void
  isFetching: boolean
  isLoading: boolean
  horizonOptions?: number[]
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 mb-4 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5">
      <div className="flex bg-white border border-slate-300 rounded-md p-0.5">
        {horizonOptions.map((n) => (
          <button
            key={n}
            onClick={() => onHorizonChange(n)}
            className={`text-xs font-medium px-2.5 py-1 rounded transition-colors ${
              horizon === n ? 'bg-emerald-600 text-white' : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            {n} GWs
          </button>
        ))}
      </div>

      <label className="flex items-center gap-1.5 text-xs text-slate-600">
        <span className="whitespace-nowrap">Free transfers banked</span>
        <input
          type="number"
          min={0}
          max={5}
          value={freeTransfersInput}
          onChange={(e) => onFreeTransfersInputChange(e.target.value)}
          onBlur={() => onFreeTransfersInputChange(String(freeTransfers))}
          className="w-12 text-xs border border-slate-300 rounded-md px-1.5 py-1 text-center"
        />
      </label>

      <label className="flex items-center gap-1.5 text-xs text-slate-600">
        <span className="whitespace-nowrap">Transfer sensitivity</span>
        <select
          value={minGain}
          onChange={(e) => onMinGainChange(Number(e.target.value))}
          className="text-xs border border-slate-300 rounded-md px-1.5 py-1 bg-white"
          title="How big an xP gain has to be before the plan suggests a transfer for it"
        >
          {MIN_GAIN_PRESETS.map((p) => (
            <option key={p.value} value={p.value} title={p.hint}>{p.label}</option>
          ))}
        </select>
      </label>

      <button
        onClick={() => onAllowHitsChange(!allowHits)}
        aria-pressed={allowHits}
        className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1.5 rounded-md border transition-colors ${
          allowHits
            ? 'bg-amber-50 border-amber-300 text-amber-800'
            : 'bg-white border-slate-300 text-slate-500 hover:bg-slate-100'
        }`}
      >
        <Zap size={12} className={allowHits ? 'fill-amber-400 text-amber-500' : ''} />
        Allow -4 hits {allowHits ? 'on' : 'off'}
      </button>

      {isFetching && !isLoading && <RefreshCw size={13} className="text-slate-400 animate-spin ml-auto" />}
    </div>
  )
}

export function GamePlanSummary({ plan, hitCost = 4 }: { plan: TeamPlanStep[]; hitCost?: number }) {
  // Defensive: an unexpected/malformed response (or a test double that
  // doesn't know about this endpoint) shouldn't crash the whole page --
  // just render as "nothing planned" rather than throwing on .reduce.
  const safePlan = Array.isArray(plan) ? plan : []
  const totals = safePlan.reduce(
    (acc, step) => ({
      points: acc.points + step.expected_points_with_captain_after_hits,
      transfers: acc.transfers + step.transfers_in.length,
      hits: acc.hits + step.hits_taken,
    }),
    { points: 0, transfers: 0, hits: 0 },
  )
  return (
    <div className="grid grid-cols-3 gap-2 mb-4">
      <SummaryTile label="Total xP (this window)" value={totals.points.toFixed(1)} accent="emerald" />
      <SummaryTile label="Transfers planned" value={String(totals.transfers)} accent="slate" />
      <SummaryTile
        label="Hits taken"
        value={totals.hits > 0 ? `${totals.hits} (-${totals.hits * hitCost})` : '0'}
        accent={totals.hits > 0 ? 'amber' : 'slate'}
      />
    </div>
  )
}

function SummaryTile({ label, value, accent }: { label: string; value: string; accent: 'emerald' | 'amber' | 'slate' }) {
  const colors = {
    emerald: 'bg-emerald-50 text-emerald-700 border-emerald-100',
    amber: 'bg-amber-50 text-amber-700 border-amber-100',
    slate: 'bg-slate-50 text-slate-700 border-slate-100',
  }[accent]
  return (
    <div className={`rounded-lg border px-3 py-2 ${colors}`}>
      <p className="text-[10px] uppercase tracking-wide opacity-70">{label}</p>
      <p className="text-lg font-bold leading-tight">{value}</p>
    </div>
  )
}

export function GamePlanTimeline({ plan }: { plan: TeamPlanStep[] }) {
  const safePlan = Array.isArray(plan) ? plan : []
  return (
    <div className="space-y-2">
      {safePlan.map((step, i) => (
        <GameplanStepRow
          key={step.gameweek}
          step={step}
          previousStep={i > 0 ? safePlan[i - 1] : undefined}
          defaultOpen={i === 0}
        />
      ))}
    </div>
  )
}

function GameplanStepRow({ step, previousStep, defaultOpen = false }: {
  step: TeamPlanStep
  previousStep?: TeamPlanStep
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const squadById = new Map(step.squad.map((p) => [p.player_id, p]))
  const diff = diffSteps(previousStep, step)
  const currFormationLabel = formationLabel(step.formation)
  const freeCount = step.transfers_in.length - step.hits_taken
  const hasTransfers = step.transfers_in.length > 0
  const transferredInSet = new Set(step.transfers_in)
  const nameOf = (id: number) => squadById.get(id)?.name ?? `#${id}`
  const subsCount = diff?.movedIntoXI.size ?? 0

  return (
    <div className={`border rounded-lg overflow-hidden transition-colors ${
      open ? 'border-emerald-200 shadow-sm' : 'border-slate-200'
    }`}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 sm:gap-3 px-3 py-2.5 text-left bg-white hover:bg-slate-50"
      >
        {open ? (
          <ChevronDown size={15} className="text-slate-400 shrink-0" />
        ) : (
          <ChevronRight size={15} className="text-slate-400 shrink-0" />
        )}
        <span className="text-sm font-bold text-slate-900 w-11 shrink-0">GW{step.gameweek}</span>
        <span className="hidden sm:inline text-[11px] font-mono w-16 shrink-0">
          {diff?.formationChanged ? (
            <span className="text-amber-700" title={`Formation changed from ${diff.prevFormationLabel}`}>
              {diff.prevFormationLabel}→{currFormationLabel}
            </span>
          ) : (
            <span className="text-slate-400">{currFormationLabel}</span>
          )}
        </span>
        <span className="text-xs text-slate-600 flex-1 truncate min-w-0">
          <span className="text-slate-400">C </span>
          <span className={`font-medium ${diff?.captainChanged ? 'text-amber-700' : 'text-slate-800'}`}>
            {step.captain}
          </span>
        </span>

        <div className="flex items-center gap-1 shrink-0">
          {subsCount > 0 && (
            <span
              className="hidden sm:flex items-center gap-1 text-[10px] bg-sky-50 text-sky-700 px-1.5 py-0.5 rounded font-medium"
              title="Starting XI changed with no transfer -- a fixture/form-driven swap"
            >
              <ArrowUpDown size={9} /> {subsCount} sub{subsCount > 1 ? 's' : ''}
            </span>
          )}
          {hasTransfers && (
            <span className="hidden sm:flex items-center gap-1 text-[10px] bg-emerald-50 text-emerald-700 px-1.5 py-0.5 rounded font-medium">
              <ArrowRight size={9} /> {step.transfers_in.length}
            </span>
          )}
          {step.hits_taken > 0 && (
            <span className="flex items-center gap-0.5 text-[10px] bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded font-semibold">
              <Zap size={9} className="fill-amber-500 text-amber-600" /> -{step.hits_taken * 4}
            </span>
          )}
        </div>


        <span className="text-sm font-bold text-emerald-700 w-16 sm:w-20 text-right shrink-0">
          {step.expected_points_with_captain_after_hits.toFixed(1)}{' '}
          <span className="text-[10px] font-normal text-emerald-600/70">xP</span>
        </span>
      </button>

      {open && (
        <div className="px-3 py-3 border-t border-slate-100 text-sm bg-slate-50/50">
          {hasTransfers && (
            <div className="mb-3">
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1.5">
                Transfers this round
              </p>
              <ul className="text-xs space-y-1">
                {step.transfers_out.map((_, i) => {
                  const isHit = i >= freeCount
                  return (
                    <li key={i} className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-red-600 line-through decoration-red-300">{step.transfers_out_names[i]}</span>
                      <ArrowRight size={11} className="text-slate-400" />
                      <span className="text-emerald-700 font-medium">{step.transfers_in_names[i]}</span>
                      {isHit ? (
                        <span className="flex items-center gap-0.5 text-[9px] bg-amber-100 text-amber-800 px-1 py-0.5 rounded font-semibold">
                          <Zap size={8} /> -4 hit
                        </span>
                      ) : (
                        <span className="text-[9px] bg-slate-100 text-slate-500 px-1 py-0.5 rounded">free</span>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          )}

          <div className="grid grid-cols-2 gap-x-4 gap-y-2">
            <div>
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Starting XI</p>
              <ul className="text-xs text-slate-700 space-y-1">
                {POSITION_ORDER.map((pos) =>
                  step.starter_ids
                    .filter((id) => squadById.get(id)?.position === pos)
                    .map((id) => (
                      <li key={id} className="flex items-center gap-1.5">
                        <span className="text-[9px] font-mono text-slate-400 w-6">{pos}</span>
                        <span className={step.captain === nameOf(id) ? 'font-semibold' : ''}>{nameOf(id)}</span>
                        {step.captain === nameOf(id) && (
                          <span className="text-[9px] font-bold bg-yellow-400 text-yellow-950 w-3.5 h-3.5 rounded-full flex items-center justify-center">C</span>
                        )}
                        {step.vice_captain === nameOf(id) && (
                          <span className="text-[9px] font-bold bg-slate-300 text-slate-700 w-3.5 h-3.5 rounded-full flex items-center justify-center">V</span>
                        )}
                        {transferredInSet.has(id) && (
                          <span className="text-[8px] font-semibold bg-emerald-100 text-emerald-700 px-1 rounded" title="New this round -- transferred in">
                            NEW
                          </span>
                        )}
                        {!transferredInSet.has(id) && diff?.movedIntoXI.has(id) && (
                          <span className="flex items-center gap-0.5 text-[8px] font-semibold bg-sky-100 text-sky-700 px-1 rounded" title="Promoted from bench, no transfer">
                            <ArrowUp size={8} /> IN
                          </span>
                        )}
                      </li>
                    )),
                )}
              </ul>
            </div>
            <div>
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1.5">
                Bench (sub priority)
              </p>
              <ul className="text-xs text-slate-500 space-y-1">
                {step.bench_ids.map((id, i) => {
                  const prevSlot = diff?.benchOrderChanges.get(id)
                  return (
                    <li key={id} className="flex items-center gap-1.5">
                      <span className="text-[9px] font-mono text-slate-300 w-3">{i + 1}</span>
                      {nameOf(id)}
                      {transferredInSet.has(id) && (
                        <span className="text-[8px] font-semibold bg-emerald-100 text-emerald-700 px-1 rounded" title="New this round -- transferred in">
                          NEW
                        </span>
                      )}
                      {!transferredInSet.has(id) && diff?.movedToBench.has(id) && (
                        <span className="flex items-center gap-0.5 text-[8px] font-semibold bg-amber-100 text-amber-800 px-1 rounded" title="Dropped from the XI, no transfer">
                          <ArrowDown size={8} /> OUT
                        </span>
                      )}
                      {prevSlot != null && (
                        <span className="text-[8px] text-slate-400" title={`Was bench slot #${prevSlot + 1} last round`}>
                          (was #{prevSlot + 1})
                        </span>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          </div>

          <div className="flex items-center gap-3 mt-3 pt-2 border-t border-slate-200/70 text-[10px] text-slate-400">
            <span className="flex items-center gap-1"><Wallet size={11} /> £{step.bank_after.toFixed(1)}m bank</span>
            <span>{step.free_transfers_after} free transfer{step.free_transfers_after === 1 ? '' : 's'} banked next</span>
          </div>
        </div>
      )}
    </div>
  )
}
