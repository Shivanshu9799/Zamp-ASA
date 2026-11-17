import { useState } from 'react'
import { CheckCircle2, Clipboard, ClipboardCheck, Mail, Phone, RefreshCw, ShieldAlert, Sparkles, ThumbsDown, ThumbsUp } from 'lucide-react'
import type { Candidate, RunDetail } from '../types'
import { fmtDateTime, fmtINR } from '../lib/format'
import { Button, Card, cx, RuleTag, StatusPill } from './ui'

const RULE_NAME: Record<string, string> = {
  R01: 'Missing fields', R02: 'Low-confidence reading', R03: 'Arithmetic', R04: 'GST structure', R05: 'Vendor', R06: 'Bank details',
  R07: 'Exact duplicate', R08: 'Probable duplicate', R09: 'PO not found', R10: 'No PO', R11: 'Unit price', R12: 'Goods received',
  R13: 'PO value', R14: 'Currency', R15: 'Total', R16: 'Addressee', SYS: 'Processing error',
}

export function DecisionCard({ run, currentStage, onApprove, onReject, onRerun }: { run: RunDetail; currentStage?: string; onApprove: () => void; onReject: () => void; onRerun: () => void }) {
  const processing = run.status === 'PROCESSING'
  const hold = !!run.decision_detail?.security_hold
  const sys = run.decision
  const human = run.audit.filter(a => a.action.endsWith('_override')).slice(-1)[0]
  const fired = run.decision_detail?.fired_rules ?? []
  const headline = processing
    ? 'Working on it…'
    : run.status === 'APPROVED' ? (human ? 'Approved by a finance user' : 'Recommended for payment')
    : run.status === 'REJECTED' ? (human ? 'Rejected by a finance user' : 'Rejected')
    : hold ? 'Held for security review' : 'Needs a human decision'
  const ring = processing ? 'ring-sky-200' : run.status === 'APPROVED' ? 'ring-emerald-200' : run.status === 'REJECTED' ? 'ring-rose-200' : 'ring-amber-200'
  const bar = processing ? 'bg-sky-500' : run.status === 'APPROVED' ? 'bg-emerald-500' : run.status === 'REJECTED' ? 'bg-rose-500' : 'bg-amber-500'
  return (
    <section className={cx('overflow-hidden rounded-2xl bg-white shadow-card ring-1', ring)}>
      <div className={cx('h-1.5', bar, processing && 'animate-pulse')} />
      <div className="grid gap-6 p-6 lg:grid-cols-[1fr_auto]">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <StatusPill status={run.status} hold={hold} size="lg" />
            <h2 className="text-xl font-semibold tracking-tight text-slate-900">{headline}</h2>
          </div>
          {processing ? (
            <p className="mt-3 text-[15px] text-slate-500">Running the checks one by one{currentStage ? ` — currently: ${currentStage}` : ''}. The decision is made by fixed rules, not by the AI.</p>
          ) : (
            <>
              <p className="mt-3 max-w-3xl text-[15px] leading-relaxed text-slate-700">{run.explanation ?? run.decision_detail?.primary_reason}</p>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                {run.explanation_source && (
                  <span className="inline-flex items-center gap-1"><Sparkles size={12} /> Wording: {run.explanation_source.startsWith('llm') ? 'AI-written from the check results' : 'generated from the check results'} · decision: fixed rules</span>
                )}
              </div>
              {human && (
                <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700 ring-1 ring-slate-200">
                  <b>{human.actor}</b> {human.action === 'approve_override' ? 'approved' : 'rejected'} this invoice on {fmtDateTime(human.ts)}: “{human.reason}”. The system’s own decision was <b>{sys}</b>.
                </div>
              )}
              <div className="mt-4 flex flex-wrap items-center gap-1.5">
                {fired.length === 0 ? (
                  <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700"><CheckCircle2 size={14} /> No rules fired</span>
                ) : (
                  <>
                    <span className="mr-1 text-xs text-slate-500">Rules that fired:</span>
                    {fired.map(r => (
                      <span key={r} className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 py-0.5 pl-2 pr-1.5 text-xs text-slate-700 ring-1 ring-slate-200">
                        {RULE_NAME[r] ?? r} <RuleTag id={r} />
                      </span>
                    ))}
                  </>
                )}
              </div>
            </>
          )}
        </div>
        <div className="flex flex-row flex-wrap items-start gap-2 lg:flex-col lg:items-stretch">
          <Button variant="success" disabled={processing || run.status === 'APPROVED'} onClick={onApprove}><ThumbsUp size={15} /> Approve</Button>
          <Button variant="danger" disabled={processing || run.status === 'REJECTED'} onClick={onReject}><ThumbsDown size={15} /> Reject</Button>
          <Button disabled={processing} onClick={onRerun}><RefreshCw size={15} /> Re-run</Button>
        </div>
      </div>
    </section>
  )
}

export function NextActionCard({ run }: { run: RunDetail }) {
  const a = run.next_action
  const [copied, setCopied] = useState(false)
  if (!a || run.status === 'PROCESSING') return null
  const copy = async () => {
    const head: string[] = []
    if (a.to) head.push(`To: ${a.to}`)
    if (a.subject) head.push(`Subject: ${a.subject}`)
    const text = [...head, '', a.body].join('\n')
    try { await navigator.clipboard.writeText(text) } catch {}
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }
  const Icon = a.channel === 'phone' ? Phone : a.channel === 'email' ? Mail : a.type === 'security_verification' ? ShieldAlert : CheckCircle2
  return (
    <Card
      title={<span className="flex items-center gap-2"><Icon size={15} className="text-slate-500" /> Next action: {a.title}</span>}
      right={a.channel !== 'none' && <Button variant="secondary" onClick={copy} className="!px-2.5 !py-1 text-xs">{copied ? <><ClipboardCheck size={13} /> Copied</> : <><Clipboard size={13} /> Copy draft</>}</Button>}
    >
      {a.note && <div className={cx('mb-3 rounded-lg px-3 py-2 text-sm ring-1', a.type === 'security_verification' ? 'bg-amber-50 text-amber-900 ring-amber-200' : 'bg-slate-50 text-slate-700 ring-slate-200')}>{a.note}</div>}
      {(a.to || a.subject) && (
        <div className="mb-2 space-y-0.5 text-sm">
          {a.to && <div><span className="text-slate-500">{a.channel === 'phone' ? 'Call' : 'To'}:</span> <span className="font-medium text-slate-800">{a.to}</span></div>}
          {a.subject && <div><span className="text-slate-500">Subject:</span> <span className="font-medium text-slate-800">{a.subject}</span></div>}
        </div>
      )}
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-4 font-sans text-[13px] leading-relaxed text-slate-700 ring-1 ring-slate-100">{a.body}</pre>
      <p className="mt-2 text-xs text-slate-400">Drafts are never sent automatically.</p>
    </Card>
  )
}

export function CandidatesCard({ run, onConfirm, busy }: { run: RunDetail; onConfirm: (po: string) => void; busy: boolean }) {
  const pc = run.po_candidates
  if (!pc || (!pc.candidates.length && !pc.excluded.length)) return null
  const resolved = !!run.po_id
  const top = pc.candidates[0]
  return (
    <Card
      title="Candidate purchase orders"
      right={resolved ? <span className="text-xs font-medium text-emerald-700">{run.po_override ? `Confirmed by a finance user: ${run.po_id}` : `Matched: ${run.po_id}`}</span> : <span className="text-xs text-slate-500">No PO number on the invoice — the agent suggests, a person confirms</span>}
    >
      {run.extracted?.po_reference_text && <p className="mb-3 text-sm text-slate-600">Invoice says: <i>“{run.extracted.po_reference_text}”</i></p>}
      <ul className="space-y-3">
        {pc.candidates.map((c: Candidate, i) => (
          <li key={c.po_id} className={cx('rounded-xl p-4 ring-1', i === 0 && c.score >= 0.75 ? 'bg-indigo-50/60 ring-indigo-200' : 'bg-white ring-slate-200')}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="font-mono text-sm font-semibold text-slate-900">{c.po_id}</span>
                <span className="text-xs text-slate-500">{c.type} · {fmtINR(c.po_amount)}</span>
                {i === 0 && c.score >= 0.75 && <span className="rounded-full bg-indigo-700 px-2 py-0.5 text-[10px] font-semibold text-white">Best match</span>}
              </div>
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2">
                  <div className="h-2 w-28 overflow-hidden rounded-full bg-slate-100"><div className={cx('h-full rounded-full', c.score >= 0.75 ? 'bg-indigo-600' : 'bg-slate-400')} style={{ width: `${c.score * 100}%` }} /></div>
                  <span className="w-10 text-right text-sm font-semibold tabular text-slate-800">{Math.round(c.score * 100)}%</span>
                </div>
                {!resolved && <Button variant={i === 0 && c.score >= 0.75 ? 'primary' : 'secondary'} disabled={busy} onClick={() => onConfirm(c.po_id)} className="!py-1.5 text-xs">Confirm PO</Button>}
              </div>
            </div>
            <ul className="mt-2 grid gap-x-6 gap-y-0.5 text-xs text-slate-600 sm:grid-cols-2">{c.reasons.map((r, j) => <li key={j}>• {r}</li>)}</ul>
          </li>
        ))}
        {pc.excluded.map(c => (
          <li key={c.po_id} className="rounded-xl bg-slate-50 p-3 text-xs text-slate-500 ring-1 ring-slate-200">
            <span className="font-mono font-semibold text-slate-600">{c.po_id}</span> — excluded. {c.reasons[0]}
          </li>
        ))}
      </ul>
      {!resolved && !top && <p className="text-sm text-slate-500">No open PO for this vendor resembles the invoice.</p>}
    </Card>
  )
}

const ACTION_LABEL: Record<string, string> = {
  created: 'Invoice received', approve_override: 'Approved manually', reject_override: 'Rejected manually', confirm_po: 'PO confirmed', rerun: 'Re-run requested',
}

export function AuditTrail({ run }: { run: RunDetail }) {
  return (
    <Card title="Audit trail">
      <ol className="relative space-y-4 border-l border-slate-200 pl-5">
        {run.audit.map(a => (
          <li key={a.id} className="relative">
            <span className="absolute -left-[26px] top-1.5 h-2.5 w-2.5 rounded-full bg-slate-300 ring-4 ring-white" />
            <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
              <span className="font-medium text-slate-800">{ACTION_LABEL[a.action] ?? a.action}</span>
              <span className="text-xs text-slate-500">by {a.actor}</span>
              <span className="text-xs text-slate-400">{fmtDateTime(a.ts)}</span>
            </div>
            {a.reason && <div className="mt-0.5 text-sm text-slate-600">{a.reason}</div>}
          </li>
        ))}
      </ol>
    </Card>
  )
}
