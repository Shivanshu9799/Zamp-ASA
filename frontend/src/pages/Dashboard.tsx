import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Search, ScanLine, ShieldAlert } from 'lucide-react'
import { api } from '../api'
import type { RunSummary, Stats } from '../types'
import { ago, fmtDateTime, fmtDuration, fmtINR } from '../lib/format'
import { Button, Card, Empty, ErrorBox, Spinner, StatusPill, cx } from '../components/ui'

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'green' | 'amber' | 'red' }) {
  const dot = tone === 'green' ? 'bg-emerald-500' : tone === 'amber' ? 'bg-amber-500' : tone === 'red' ? 'bg-rose-500' : 'bg-slate-300'
  return (
    <div className="rounded-xl bg-white p-4 shadow-card ring-1 ring-slate-200/80">
      <div className="flex items-center gap-2 text-xs font-medium text-slate-500"><span className={cx('h-2 w-2 rounded-full', dot)} />{label}</div>
      <div className="mt-2 text-2xl font-semibold tracking-tight text-slate-900 tabular">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500 tabular">{sub}</div>}
    </div>
  )
}

const TABS = [['ALL', 'All'], ['APPROVED', 'Approved'], ['PENDING', 'Pending'], ['REJECTED', 'Rejected']] as const
const PAGE = 15

export default function Dashboard() {
  const nav = useNavigate()
  const [stats, setStats] = useState<Stats | null>(null)
  const [rows, setRows] = useState<RunSummary[] | null>(null)
  const [total, setTotal] = useState(0)
  const [status, setStatus] = useState('ALL')
  const [vendor, setVendor] = useState('')
  const [q, setQ] = useState('')
  const [dq, setDq] = useState('')
  const [page, setPage] = useState(1)
  const [vendors, setVendors] = useState<{ id: string; name: string }[]>([])
  const [err, setErr] = useState('')

  useEffect(() => { api.master('vendors').then(setVendors).catch(() => {}) }, [])
  useEffect(() => { const t = setTimeout(() => { setDq(q); setPage(1) }, 250); return () => clearTimeout(t) }, [q])

  const load = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([api.stats(), api.runs({ status, vendor, q: dq, page, page_size: PAGE })])
      setStats(s); setRows(r.items); setTotal(r.total); setErr('')
    } catch (e: any) { setErr(e.message) }
  }, [status, vendor, dq, page])
  useEffect(() => { load(); const t = setInterval(load, 4000); return () => clearInterval(t) }, [load])

  if (err && !rows) return <ErrorBox message={err} onRetry={load} />
  if (!stats || !rows) return <Spinner />

  const maxReason = Math.max(1, ...stats.top_exception_reasons.map(r => r.count))
  const pendingVal = stats.value_by_status.PENDING
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">Invoice dashboard</h1>
          <p className="text-sm text-slate-500">Every invoice that has been through the agent, with the reason behind each decision.</p>
        </div>
        <Link to="/new"><Button variant="primary">Process an invoice</Button></Link>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Kpi label="Invoices processed" value={String(stats.processed)} sub={stats.by_status.PROCESSING ? `${stats.by_status.PROCESSING} running now` : undefined} />
        <Kpi label="Auto-approved" value={`${Math.round(stats.auto_approval_rate * 100)}%`} sub={`${stats.auto_approved} of ${stats.processed} with no human touch`} tone="green" />
        <Kpi label="Pending review" value={String(stats.by_status.PENDING)} sub={`${fmtINR(pendingVal)} on hold${stats.security_holds ? ` · ${stats.security_holds} security` : ''}`} tone="amber" />
        <Kpi label="Rejected" value={String(stats.by_status.REJECTED)} sub={fmtINR(stats.value_by_status.REJECTED)} tone="red" />
        <Kpi label="Avg processing time" value={fmtDuration(stats.avg_processing_ms)} sub="compute time per invoice" />
      </div>

      <div className="space-y-5">
        <Card title="Top exception reasons" right={<span className="text-xs text-slate-500">why invoices were held or rejected</span>}>
          {stats.top_exception_reasons.length === 0 ? (
            <p className="py-3 text-center text-sm text-slate-500">No exceptions yet — everything so far passed all checks.</p>
          ) : (
            <ul className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
              {stats.top_exception_reasons.map(r => (
                <li key={r.rule_id}>
                  <div className="flex items-baseline justify-between text-sm"><span className="text-slate-700">{r.label} <span className="font-mono text-[10px] text-slate-400">{r.rule_id}</span></span><span className="font-semibold tabular text-slate-900">{r.count}</span></div>
                  <div className="mt-1 h-1.5 rounded-full bg-slate-100"><div className="h-full rounded-full bg-amber-500" style={{ width: `${(r.count / maxReason) * 100}%` }} /></div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card pad={false} title="Invoices"
          right={
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex rounded-lg bg-slate-100 p-0.5 text-xs font-medium">
                {TABS.map(([k, l]) => (
                  <button key={k} onClick={() => { setStatus(k); setPage(1) }} className={cx('rounded-md px-2.5 py-1 transition', status === k ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800')}>{l}</button>
                ))}
              </div>
              <select value={vendor} onChange={e => { setVendor(e.target.value); setPage(1) }} className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700">
                <option value="">All vendors</option>
                {vendors.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
              </select>
              <div className="relative"><Search size={13} className="absolute left-2 top-2 text-slate-400" /><input value={q} onChange={e => setQ(e.target.value)} placeholder="Search" className="w-32 rounded-lg border border-slate-200 py-1.5 pl-7 pr-2 text-xs outline-none focus:border-indigo-400" /></div>
            </div>
          }>
          {rows.length === 0 ? (
            <Empty title={stats.processed === 0 ? 'No invoices yet' : 'No invoices match these filters'} hint={stats.processed === 0 ? 'Run one of the sample invoices to see the agent work.' : undefined} action={stats.processed === 0 ? <Link to="/new"><Button variant="primary">Process an invoice</Button></Link> : undefined} />
          ) : (
            <div className="overflow-x-auto scroll-thin">
              <table className="w-full min-w-[860px] text-sm">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50/70 text-left text-[11px] uppercase tracking-wide text-slate-500">
                    <th className="px-4 py-2 font-medium">When</th><th className="px-3 font-medium">Vendor</th><th className="px-3 font-medium">Invoice</th><th className="px-3 font-medium">PO</th>
                    <th className="px-3 text-right font-medium">Amount</th><th className="px-3 font-medium">Status</th><th className="px-3 font-medium">Main reason</th><th className="px-4 text-right font-medium">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(r => (
                    <tr key={r.id} onClick={() => nav(`/runs/${r.id}`)} className="cursor-pointer border-b border-slate-100 transition hover:bg-indigo-50/40">
                      <td className="px-4 py-3 text-xs text-slate-500" title={fmtDateTime(r.created_at)}>#{r.id} · {ago(r.created_at)}</td>
                      <td className="px-3 text-slate-800">{r.vendor_name ?? <span className="text-slate-400">—</span>}</td>
                      <td className="px-3 font-mono text-[13px] text-slate-700">{r.invoice_number ?? '—'} {r.scanned && <ScanLine size={12} className="ml-1 inline text-slate-400" />}</td>
                      <td className="px-3 font-mono text-xs text-slate-500">{r.po_id ?? '—'}</td>
                      <td className="px-3 text-right font-medium tabular text-slate-900">{fmtINR(r.total)}</td>
                      <td className="px-3"><StatusPill status={r.status} hold={r.security_hold} /></td>
                      <td className="max-w-[260px] truncate px-3 text-xs text-slate-600" title={r.reason ?? ''}>{r.security_hold && r.status === 'PENDING' && <ShieldAlert size={12} className="mr-1 inline text-amber-600" />}{r.status === 'PROCESSING' ? 'Running…' : r.reason}</td>
                      <td className="px-4 text-right text-xs tabular text-slate-500">{fmtDuration(r.duration_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {total > PAGE && (
            <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2.5 text-xs text-slate-500">
              <span>{(page - 1) * PAGE + 1}–{Math.min(page * PAGE, total)} of {total}</span>
              <div className="flex gap-2"><Button variant="secondary" className="!py-1 text-xs" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</Button><Button variant="secondary" className="!py-1 text-xs" disabled={page * PAGE >= total} onClick={() => setPage(page + 1)}>Next</Button></div>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
