import { useState } from 'react'
import { AlertTriangle, Check, ChevronRight, Info, Minus, ShieldAlert, X } from 'lucide-react'
import type { Check as CheckT, StageRow } from '../types'
import { Card, cx, RuleTag } from './ui'
import { STAGES } from './Stepper'

function Icon({ c }: { c: CheckT }) {
  if (c.status === 'pass') return <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-100 text-emerald-700"><Check size={12} strokeWidth={3} /></span>
  if (c.status === 'skipped') return <span className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-100 text-slate-400"><Minus size={12} /></span>
  if (c.status === 'warn') return <span className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-100 text-slate-500"><Info size={12} /></span>
  if (c.severity === 'security') return <span className="flex h-5 w-5 items-center justify-center rounded-full bg-amber-100 text-amber-800"><ShieldAlert size={12} /></span>
  if (c.severity === 'reject') return <span className="flex h-5 w-5 items-center justify-center rounded-full bg-rose-100 text-rose-700"><X size={12} strokeWidth={3} /></span>
  return <span className="flex h-5 w-5 items-center justify-center rounded-full bg-amber-100 text-amber-700"><AlertTriangle size={11} /></span>
}

function fmtVal(v: any): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function Evidence({ ev }: { ev: Record<string, any> }) {
  const skip = new Set(['lines', 'candidates', 'excluded', 'crosscheck'])
  const rows = Object.entries(ev).filter(([k, v]) => !skip.has(k) && v !== null && v !== undefined && v !== '')
  return (
    <div className="mt-2 rounded-md bg-slate-50 p-3 ring-1 ring-slate-100">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
        {rows.map(([k, v]) => (
          <div key={k} className="flex gap-2">
            <dt className="shrink-0 text-slate-500">{k.replace(/_/g, ' ')}:</dt>
            <dd className="break-all font-mono text-slate-800">{fmtVal(v)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function Row({ c }: { c: CheckT }) {
  const [open, setOpen] = useState(false)
  const has = Object.keys(c.evidence ?? {}).length > 0
  return (
    <li className="py-2.5">
      <div className="flex items-start gap-3">
        <Icon c={c} />
        <div className="min-w-0 flex-1">
          <div className="text-sm text-slate-800">{c.message}</div>
          <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-400">
            <RuleTag id={c.rule_id} /> <span>{c.name}</span>
            {has && (
              <button onClick={() => setOpen(!open)} className="ml-1 inline-flex items-center gap-0.5 text-indigo-600 hover:underline">
                <ChevronRight size={11} className={cx('transition', open && 'rotate-90')} /> evidence
              </button>
            )}
          </div>
          {open && <Evidence ev={c.evidence} />}
        </div>
      </div>
    </li>
  )
}

export function ChecksList({ stages }: { stages: StageRow[] }) {
  const groups = STAGES.map(s => ({ s, rows: stages.find(x => x.stage === s.key)?.checks ?? [] })).filter(g => g.rows.length)
  if (!groups.length) return null
  const total = groups.flatMap(g => g.rows)
  return (
    <Card title="What was checked" right={<span className="text-xs text-slate-500">{total.filter(c => c.status === 'pass').length} passed · {total.filter(c => c.status === 'warn').length} notes · {total.filter(c => c.status === 'fail').length} failed{total.some(c => c.status === 'skipped') ? ` · ${total.filter(c => c.status === 'skipped').length} not evaluated` : ''}</span>}>
      <div className="space-y-5">
        {groups.map(({ s, rows }) => (
          <div key={s.key}>
            <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{s.label}</div>
            <ul className="divide-y divide-slate-100">{rows.map((c, i) => <Row key={i} c={c} />)}</ul>
          </div>
        ))}
      </div>
    </Card>
  )
}
