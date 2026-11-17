import { useState } from 'react'
import { AlertTriangle, Check, ChevronDown, Loader2, Minus, X } from 'lucide-react'
import type { Check as CheckT, StageStatus } from '../types'
import { fmtDuration } from '../lib/format'
import { cx, RuleTag } from './ui'

export const STAGES = [
  { key: 'intake', label: 'Intake' },
  { key: 'extract', label: 'Extract' },
  { key: 'validate', label: 'Validate' },
  { key: 'vendor', label: 'Vendor' },
  { key: 'duplicate', label: 'Duplicate' },
  { key: 'po_match', label: 'PO match' },
  { key: 'decision', label: 'Decision' },
  { key: 'explain', label: 'Next action' },
]

export interface StageView {
  status: StageStatus
  duration_ms: number | null
  summary: string
  checks: CheckT[]
}

function Node({ status }: { status: StageStatus }) {
  const base = 'relative z-10 flex h-9 w-9 items-center justify-center rounded-full ring-2 transition-all duration-300'
  switch (status) {
    case 'running':
      return <div className={cx(base, 'bg-sky-600 text-white ring-sky-200 animate-pulseRing')}><Loader2 size={18} className="animate-spin" /></div>
    case 'passed':
      return <div className={cx(base, 'bg-emerald-600 text-white ring-emerald-200')}><Check size={18} strokeWidth={3} /></div>
    case 'warning':
      return <div className={cx(base, 'bg-amber-500 text-white ring-amber-200')}><AlertTriangle size={17} /></div>
    case 'failed':
      return <div className={cx(base, 'bg-rose-600 text-white ring-rose-200')}><X size={18} strokeWidth={3} /></div>
    case 'skipped':
      return <div className={cx(base, 'bg-slate-200 text-slate-500 ring-slate-100')}><Minus size={16} /></div>
    default:
      return <div className={cx(base, 'bg-white text-slate-300 ring-slate-200')}><span className="h-2 w-2 rounded-full bg-slate-300" /></div>
  }
}

const LABEL_COLOR: Record<string, string> = {
  running: 'text-sky-700', passed: 'text-slate-800', warning: 'text-amber-700', failed: 'text-rose-700', skipped: 'text-slate-400', pending: 'text-slate-400',
}

export function Stepper({ stages }: { stages: Record<string, StageView> }) {
  const [open, setOpen] = useState<string | null>(null)
  const sel = open ? stages[open] : null
  return (
    <div>
      <div className="overflow-x-auto scroll-thin">
        <ol className="flex min-w-[720px] items-start">
          {STAGES.map((s, i) => {
            const v = stages[s.key] ?? { status: 'pending' as StageStatus, duration_ms: null, summary: '', checks: [] }
            const prev = i > 0 ? stages[STAGES[i - 1].key]?.status : undefined
            const lineOn = prev && prev !== 'pending' && prev !== 'running'
            return (
              <li key={s.key} className="relative flex flex-1 flex-col items-center">
                {i > 0 && <div className={cx('absolute right-1/2 top-[18px] h-0.5 w-full transition-colors duration-500', lineOn ? 'bg-emerald-300' : 'bg-slate-200')} />}
                <button
                  onClick={() => v.status !== 'pending' && setOpen(open === s.key ? null : s.key)}
                  className="group flex flex-col items-center gap-1.5 focus:outline-none"
                  title={v.summary}
                >
                  <Node status={v.status} />
                  <span className={cx('text-xs font-semibold', LABEL_COLOR[v.status])}>{s.label}</span>
                  <span className="h-4 text-[11px] text-slate-400 tabular">
                    {v.status === 'running' ? 'working…' : v.status === 'pending' ? '' : v.status === 'skipped' ? 'skipped' : fmtDuration(v.duration_ms)}
                  </span>
                  {v.status !== 'pending' && v.status !== 'running' && (
                    <ChevronDown size={12} className={cx('text-slate-300 transition group-hover:text-slate-500', open === s.key && 'rotate-180 text-slate-600')} />
                  )}
                </button>
              </li>
            )
          })}
        </ol>
      </div>
      {open && sel && (
        <div className="mt-3 animate-rise rounded-lg bg-slate-50 p-4 ring-1 ring-slate-200">
          <div className="text-sm font-medium text-slate-800">{STAGES.find(s => s.key === open)?.label}</div>
          <div className="mt-0.5 text-sm text-slate-600">{sel.summary || '—'}</div>
          {sel.checks.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {sel.checks.map((c, i) => (
                <li key={i} className="flex items-start gap-2 text-[13px]">
                  <span className={cx('mt-1 h-2 w-2 shrink-0 rounded-full', c.status === 'pass' ? 'bg-emerald-500' : c.status === 'skipped' ? 'bg-slate-300' : c.status === 'warn' ? 'bg-amber-400' : c.severity === 'reject' ? 'bg-rose-500' : 'bg-amber-500')} />
                  <span className="text-slate-700">{c.message}</span>
                  <RuleTag id={c.rule_id} />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
