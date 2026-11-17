import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, ExternalLink, FileText } from 'lucide-react'
import { api } from '../api'
import type { RunDetail, StageStatus } from '../types'
import { fmtDateTime } from '../lib/format'
import { Button, Card, ErrorBox, Modal, Spinner } from '../components/ui'
import { Stepper, STAGES, StageView } from '../components/Stepper'
import { DecisionCard, NextActionCard, CandidatesCard, AuditTrail } from '../components/DecisionCard'
import { ExtractedPanel } from '../components/ExtractedPanel'
import { MatchTable, POBalanceBar } from '../components/MatchTable'
import { ChecksList } from '../components/ChecksList'

export default function RunView() {
  const { id } = useParams()
  const [run, setRun] = useState<RunDetail | null>(null)
  const [err, setErr] = useState('')
  const [live, setLive] = useState<Record<string, StageView>>({})
  const [streamKey, setStreamKey] = useState(0)
  const [modal, setModal] = useState<'approve' | 'reject' | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionErr, setActionErr] = useState('')

  const refetch = useCallback(async () => {
    try {
      setRun(await api.run(id!))
      setErr('')
    } catch (e: any) {
      setErr(e.message)
    }
  }, [id])

  useEffect(() => { setRun(null); setLive({}); refetch() }, [id, refetch])

  // live stage events (SSE) — replays everything on connect, so opening a finished run also works
  useEffect(() => {
    const es = new EventSource(`/api/runs/${id}/events`)
    es.addEventListener('stage', (e: MessageEvent) => {
      const ev = JSON.parse(e.data)
      setLive(prev => ({ ...prev, [ev.stage]: { status: ev.status as StageStatus, duration_ms: ev.duration_ms, summary: ev.summary, checks: ev.details?.checks ?? [] } }))
      if (ev.status !== 'running') refetch()
    })
    es.addEventListener('done', () => { es.close(); refetch() })
    return () => es.close()
  }, [id, streamKey, refetch])

  const stages = useMemo(() => {
    const out: Record<string, StageView> = {}
    for (const s of STAGES) {
      const fromRun = run?.stages.find(x => x.stage === s.key)
      const l = live[s.key]
      if (l) out[s.key] = l
      else if (fromRun) out[s.key] = { status: fromRun.status, duration_ms: fromRun.duration_ms, summary: fromRun.summary, checks: fromRun.checks }
    }
    return out
  }, [run, live])

  const runningLabel = STAGES.find(s => stages[s.key]?.status === 'running')?.label

  const act = async (body: Parameters<typeof api.action>[1]) => {
    setBusy(true)
    setActionErr('')
    try {
      const r = await api.action(run!.id, body)
      setRun(r)
      if (body.type === 'confirm_po' || body.type === 'rerun') { setLive({}); setStreamKey(k => k + 1) }
      setModal(null)
      setReason('')
    } catch (e: any) {
      setActionErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (err && !run) return <ErrorBox message={err} onRetry={refetch} />
  if (!run) return <Spinner label="Loading run…" />

  const showMatch = !!run.line_matches?.length
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to="/" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800"><ArrowLeft size={13} /> Dashboard</Link>
          <h1 className="mt-1 flex flex-wrap items-baseline gap-x-3 text-xl font-semibold tracking-tight text-slate-900">
            Run #{run.id}
            <span className="text-base font-normal text-slate-500">{run.invoice_number ?? run.file_name}{run.vendor_name ? ` · ${run.vendor_name}` : ''}</span>
          </h1>
          <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-400"><FileText size={12} /> {run.file_name} · {fmtDateTime(run.created_at)} · {run.source}{run.scanned && ' · scanned image'}</div>
        </div>
      </div>

      {actionErr && <ErrorBox message={actionErr} />}

      <Card title="Live run" right={<span className="text-xs text-slate-400">Click a step to see what it checked</span>}>
        <Stepper stages={stages} />
      </Card>

      <DecisionCard run={run} currentStage={runningLabel} onApprove={() => setModal('approve')} onReject={() => setModal('reject')} onRerun={() => act({ type: 'rerun' })} />

      {!run.po_id && <CandidatesCard run={run} busy={busy} onConfirm={po => act({ type: 'confirm_po', po_id: po, reason: `Confirmed ${po} from the suggestions` })} />}
      {run.status !== 'PROCESSING' && <NextActionCard run={run} />}
      {run.po_id && run.po_override && <CandidatesCard run={run} busy={busy} onConfirm={() => {}} />}

      <div className="grid gap-5 lg:grid-cols-12">
        <div className="lg:col-span-5">
          <div className="lg:sticky lg:top-4">
            <Card title="Original invoice" right={<a className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:underline" href={`/api/runs/${run.id}/file`} target="_blank" rel="noreferrer">Open <ExternalLink size={11} /></a>} pad={false}>
              <iframe title="Invoice PDF" src={`/api/runs/${run.id}/file#toolbar=0&navpanes=0&view=FitH`} className="h-[640px] w-full rounded-b-xl bg-slate-100 lg:h-[760px]" />
            </Card>
          </div>
        </div>
        <div className="space-y-5 lg:col-span-7">
          <ExtractedPanel run={run} />
          {showMatch && <MatchTable lines={run.line_matches!} poId={run.po_id} />}
          {run.po_balance && <POBalanceBar b={run.po_balance} />}
        </div>
      </div>

      <ChecksList stages={run.stages} />
      <AuditTrail run={run} />

      <Modal
        open={!!modal}
        onClose={() => setModal(null)}
        title={modal === 'approve' ? 'Approve this invoice' : 'Reject this invoice'}
        footer={<>
          <Button variant="ghost" onClick={() => setModal(null)}>Cancel</Button>
          <Button variant={modal === 'approve' ? 'success' : 'danger'} disabled={busy || reason.trim().length < 3} onClick={() => act({ type: modal!, reason })}>{modal === 'approve' ? 'Approve' : 'Reject'}</Button>
        </>}
      >
        <p>The system decided <b>{run.decision ?? '—'}</b>{run.decision_detail?.fired_rules?.length ? ` (rules fired: ${run.decision_detail.fired_rules.join(', ')})` : ''}. A manual override is recorded in the audit trail with your reason.</p>
        <textarea autoFocus value={reason} onChange={e => setReason(e.target.value)} placeholder="Reason (required)" rows={3} className="mt-3 w-full rounded-lg border border-slate-300 p-2.5 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200" />
        {actionErr && <div className="mt-2 text-xs text-rose-600">{actionErr}</div>}
      </Modal>
    </div>
  )
}
