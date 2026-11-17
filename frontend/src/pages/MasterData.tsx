import { Fragment, useEffect, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { api } from '../api'
import type { AppConfig } from '../types'
import { fmtDate, fmtINR, fmtQty, num } from '../lib/format'
import { Card, Spinner, cx, ErrorBox } from '../components/ui'

const TABS = ['Vendors', 'Purchase orders', 'Goods receipts', 'Rules & tolerances'] as const
type Tab = (typeof TABS)[number]

const TH = 'px-4 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-slate-500'

function Vendors() {
  const [d, setD] = useState<any[] | null>(null)
  useEffect(() => { api.master('vendors').then(setD) }, [])
  if (!d) return <Spinner />
  return (
    <Card pad={false}>
      <div className="overflow-x-auto scroll-thin"><table className="w-full min-w-[820px] text-sm">
        <thead className="bg-slate-50/70"><tr><th className={TH}>ID</th><th className={TH}>Vendor</th><th className={TH}>GSTIN</th><th className={TH}>Bank on file</th><th className={TH}>Phone on file</th></tr></thead>
        <tbody>{d.map(v => (
          <tr key={v.id} className="border-t border-slate-100 align-top">
            <td className="px-4 py-3 font-mono text-xs text-slate-500">{v.id}</td>
            <td className="px-4 py-3"><div className="font-medium text-slate-900">{v.name}</div><div className="text-xs text-slate-500">aka {v.aliases.join(', ')}</div></td>
            <td className="px-4 py-3 font-mono text-xs">{v.gstin}</td>
            <td className="px-4 py-3 text-xs"><div>{v.bank_name}</div><div className="font-mono text-slate-500">{v.account_number} · {v.ifsc}</div></td>
            <td className="px-4 py-3 text-xs text-slate-600">{v.phone_on_file}</td>
          </tr>))}</tbody>
      </table></div>
    </Card>
  )
}

function POs() {
  const [d, setD] = useState<any[] | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  useEffect(() => { api.master('pos').then(setD) }, [])
  if (!d) return <Spinner />
  return (
    <Card pad={false}>
      <div className="overflow-x-auto scroll-thin"><table className="w-full min-w-[900px] text-sm">
        <thead className="bg-slate-50/70"><tr><th className={TH}></th><th className={TH}>PO</th><th className={TH}>Vendor</th><th className={TH}>Type</th><th className={TH}>Date</th><th className={cx(TH, 'text-right')}>PO value (ex-GST)</th><th className={cx(TH, 'w-64')}>Billed so far</th></tr></thead>
        <tbody>{d.map(po => {
          const amt = num(po.amount), inv = num(po.invoiced_to_date), rev = num(po.in_review)
          return (
            <Fragment key={po.id}>
              <tr className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" onClick={() => setOpen(open === po.id ? null : po.id)}>
                <td className="pl-4"><ChevronRight size={14} className={cx('text-slate-400 transition', open === po.id && 'rotate-90')} /></td>
                <td className="px-4 py-3 font-mono text-xs font-medium text-slate-800">{po.id}{po.note?.startsWith('Decoy') && <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 font-sans text-[10px] text-slate-500">decoy</span>}</td>
                <td className="px-4 py-3 text-slate-700">{po.vendor_name}</td>
                <td className="px-4 py-3 text-xs capitalize text-slate-600">{po.type}</td>
                <td className="px-4 py-3 text-xs text-slate-600">{fmtDate(po.date)}</td>
                <td className="px-4 py-3 text-right font-medium tabular">{fmtINR(po.amount)}</td>
                <td className="px-4 py-3">
                  <div className="flex h-2 overflow-hidden rounded-full bg-slate-100"><div className="bg-slate-700" style={{ width: `${(inv / amt) * 100}%` }} /><div className="hatch" style={{ width: `${(rev / amt) * 100}%` }} /></div>
                  <div className="mt-1 flex justify-between text-[11px] tabular text-slate-500"><span>{fmtINR(po.invoiced_to_date)} billed</span><span>{fmtINR(po.remaining)} left</span></div>
                  {rev > 0 && <div className="text-[11px] text-amber-700">{fmtINR(po.in_review)} in review (not counted)</div>}
                </td>
              </tr>
              {open === po.id && (
                <tr className="bg-slate-50/60"><td /><td colSpan={6} className="px-4 pb-4 pt-1">
                  <table className="w-full text-xs tabular"><thead><tr className="text-left text-slate-500"><th className="py-1 font-medium">#</th><th className="font-medium">Item</th><th className="text-right font-medium">Ordered</th>{po.type === 'goods' && <th className="text-right font-medium">Received</th>}<th className="text-right font-medium">Billed qty</th><th className="text-right font-medium">Unit price</th></tr></thead>
                    <tbody>{po.lines.map((l: any) => <tr key={l.line_no} className="border-t border-slate-200"><td className="py-1.5">{l.line_no}</td><td>{l.description}</td><td className="text-right">{fmtQty(l.qty)} {l.uom}</td>{po.type === 'goods' && <td className="text-right">{fmtQty(l.received)}</td>}<td className="text-right">{fmtQty(l.invoiced_qty)}</td><td className="text-right">{fmtINR(l.unit_price)}</td></tr>)}</tbody></table>
                </td></tr>
              )}
            </Fragment>)
        })}</tbody>
      </table></div>
    </Card>
  )
}

function GRNs() {
  const [d, setD] = useState<any[] | null>(null)
  useEffect(() => { api.master('grns').then(setD) }, [])
  if (!d) return <Spinner />
  return (
    <Card pad={false}>
      <table className="w-full text-sm">
        <thead className="bg-slate-50/70"><tr><th className={TH}>GRN</th><th className={TH}>PO</th><th className={TH}>PO line</th><th className={cx(TH, 'text-right')}>Qty received</th><th className={TH}>Date</th></tr></thead>
        <tbody>{d.map(g => <tr key={g.id} className="border-t border-slate-100"><td className="px-4 py-2.5 font-mono text-xs">{g.id}</td><td className="px-4 font-mono text-xs text-slate-600">{g.po_id}</td><td className="px-4 text-slate-600">{g.line_no}</td><td className="px-4 text-right tabular">{fmtQty(g.qty)}</td><td className="px-4 text-xs text-slate-600">{fmtDate(g.date)}</td></tr>)}</tbody>
      </table>
    </Card>
  )
}

function Rules() {
  const [c, setC] = useState<AppConfig | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => { api.config().then(setC).catch(e => setErr(e.message)) }, [])
  if (err) return <ErrorBox message={err} />
  if (!c) return <Spinner />
  const T = c.tolerances
  const tol: [string, string, string][] = [
    ['Unit price vs PO', `±${T.PRICE_TOLERANCE_PCT}%`, 'PRICE_TOLERANCE_PCT'],
    ['Arithmetic rounding', `₹${T.TOTAL_ROUNDING_ABS}`, 'TOTAL_ROUNDING_ABS'],
    ['Quantity over-billing', `${T.QTY_TOLERANCE} units`, 'QTY_TOLERANCE'],
    ['Vendor name: auto-accept at', `${T.VENDOR_FUZZY_AUTO}% match`, 'VENDOR_FUZZY_AUTO'],
    ['Vendor name: send to review at', `${T.VENDOR_FUZZY_REVIEW}% match`, 'VENDOR_FUZZY_REVIEW'],
    ['PO suggestion needs a score of', `${Math.round(Number(T.PO_INFERENCE_SUGGEST) * 100)}%`, 'PO_INFERENCE_SUGGEST'],
    ['Duplicate date window', `${T.DUP_DATE_WINDOW_DAYS} days`, 'DUP_DATE_WINDOW_DAYS'],
    ['Invoice-number similarity for duplicates', `${T.DUP_INVOICE_NO_SIMILARITY}%`, 'DUP_INVOICE_NO_SIMILARITY'],
    ['Minimum extraction confidence', `${Math.round(Number(T.EXTRACTION_MIN_CONFIDENCE) * 100)}%`, 'EXTRACTION_MIN_CONFIDENCE'],
  ]
  const onFail = (s: string) => s.includes('REJECT') ? 'bg-rose-50 text-rose-700 ring-rose-200' : s.includes('SECURITY') ? 'bg-amber-100 text-amber-900 ring-amber-300' : 'bg-amber-50 text-amber-800 ring-amber-200'
  return (
    <div className="space-y-5">
      <Card title="Decision rules" right={<span className="text-xs text-slate-500">AI reads and explains · these rules decide</span>} pad={false}>
        <div className="overflow-x-auto scroll-thin"><table className="w-full min-w-[760px] text-sm">
          <thead className="bg-slate-50/70"><tr><th className={TH}>Rule</th><th className={TH}>Check</th><th className={TH}>If it fails</th></tr></thead>
          <tbody>{c.rules.map(r => (
            <tr key={r.id} className="border-t border-slate-100 align-top">
              <td className="px-4 py-3 font-mono text-xs text-slate-500">{r.id}</td>
              <td className="px-4 py-3"><div className="font-medium text-slate-800">{r.name}</div><div className="text-xs text-slate-500">{r.plain}</div></td>
              <td className="px-4 py-3"><span className={cx('rounded-full px-2 py-0.5 text-[11px] font-medium ring-1', onFail(r.on_fail))}>{r.on_fail}</span></td>
            </tr>))}</tbody>
        </table></div>
        <div className="border-t border-slate-100 px-4 py-3 text-xs text-slate-500">Precedence: any reject rule → <b>Reject</b>; else a security hold → <b>Pending (security)</b>; else any pending rule → <b>Pending</b>; else <b>Approve</b>. All fired rules are listed, not just the first.</div>
      </Card>
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Tolerances"><dl className="divide-y divide-slate-100">{tol.map(([l, v, k]) => <div key={k} className="flex items-baseline justify-between py-2 text-sm"><dt className="text-slate-600">{l} <span className="font-mono text-[10px] text-slate-400">{k}</span></dt><dd className="font-semibold tabular text-slate-900">{v}</dd></div>)}</dl></Card>
        <Card title="How the AI is used">
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between"><dt className="text-slate-600">Extraction mode</dt><dd className="font-semibold">{c.llm.mode}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-600">Model</dt><dd className="font-mono text-xs">{c.llm.model}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-600">API key configured</dt><dd className="font-semibold">{c.llm.api_key_configured ? 'yes' : 'no (pre-recorded extractions only)'}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-600">Buyer entity</dt><dd className="text-right text-xs">{c.buyer.name}<br />GSTIN {c.buyer.gstin} · state {c.buyer.state_code}</dd></div>
          </dl>
          <p className="mt-4 text-xs leading-relaxed text-slate-500">The model reads the PDF into structured fields and later words an explanation. It never decides, never does arithmetic on money and never sees the decision before the rules have made it. PO-inference weights: {Object.entries(c.po_inference_weights).map(([k, v]) => `${k.replace('_', '/')} ${Math.round(v * 100)}%`).join(', ')}; the vendor must match.</p>
        </Card>
      </div>
    </div>
  )
}

export default function MasterData() {
  const [tab, setTab] = useState<Tab>('Vendors')
  return (
    <div className="space-y-5">
      <div><h1 className="text-xl font-semibold tracking-tight text-slate-900">Master data & rules</h1><p className="text-sm text-slate-500">The reference data every invoice is checked against (read-only, synthetic).</p></div>
      <div className="flex gap-1 border-b border-slate-200">
        {TABS.map(t => <button key={t} onClick={() => setTab(t)} className={cx('-mb-px border-b-2 px-4 py-2 text-sm font-medium transition', tab === t ? 'border-indigo-700 text-indigo-800' : 'border-transparent text-slate-500 hover:text-slate-800')}>{t}</button>)}
      </div>
      {tab === 'Vendors' && <Vendors />}
      {tab === 'Purchase orders' && <POs />}
      {tab === 'Goods receipts' && <GRNs />}
      {tab === 'Rules & tolerances' && <Rules />}
    </div>
  )
}
