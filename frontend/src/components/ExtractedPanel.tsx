import { CheckCircle2, ScanLine, Sparkles, TriangleAlert } from 'lucide-react'
import type { RunDetail } from '../types'
import { fmtDate, fmtINR, fmtQty } from '../lib/format'
import { Card, ConfBadge, cx } from './ui'

const SOURCE: Record<string, string> = {
  llm_live: 'LLM (live)',
  llm_cached: 'LLM (cached)',
  seed_cached: 'Pre-recorded extraction (cached)',
}

function Field({ label, value, conf, found, mono, hint }: { label: string; value: React.ReactNode; conf?: number; found?: boolean; mono?: boolean; hint?: string }) {
  const low = conf !== undefined && conf < 0.8
  const bad = found === false
  return (
    <div className={cx('rounded-lg px-3 py-2', (low || bad) ? 'bg-amber-50 ring-1 ring-amber-200' : 'bg-slate-50/70')}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</span>
        <span className="flex items-center gap-1">
          {found === true && <span title="Found in the PDF's own text layer"><CheckCircle2 size={12} className="text-emerald-500" /></span>}
          {bad && <span title="NOT found in the PDF's text layer"><TriangleAlert size={12} className="text-amber-600" /></span>}
          <ConfBadge value={conf} />
        </span>
      </div>
      <div className={cx('mt-0.5 break-words text-sm text-slate-900', mono && 'font-mono text-[13px] tabular')}>{value || <span className="text-slate-400">—</span>}</div>
      {hint && <div className="mt-0.5 text-[11px] text-slate-400">{hint}</div>}
    </div>
  )
}

export function ExtractedPanel({ run }: { run: RunDetail }) {
  const ex = run.extracted
  const info = run.extraction_info
  const cc = info?.crosscheck
  if (!ex) {
    return (
      <Card title="Extracted data">
        <div className="py-8 text-center text-sm text-slate-500">{run.status === 'PROCESSING' ? 'Reading the invoice…' : 'No data could be extracted.'}</div>
      </Card>
    )
  }
  const conf = ex.field_confidence
  const f = (k: string) => cc?.fields?.[k]?.found_in_text
  return (
    <Card
      title="Extracted data"
      right={
        <div className="flex flex-wrap items-center justify-end gap-1.5 text-[11px]">
          {info && (
            <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 font-medium text-indigo-700 ring-1 ring-indigo-200">
              <Sparkles size={11} /> {SOURCE[info.source] ?? info.source}
            </span>
          )}
          {cc?.available ? (
            <span className={cx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium ring-1', cc.agreed ? 'bg-emerald-50 text-emerald-700 ring-emerald-200' : 'bg-amber-50 text-amber-800 ring-amber-300')}>
              {cc.agreed ? <CheckCircle2 size={11} /> : <TriangleAlert size={11} />} {cc.agreed ? 'Text layer agrees' : 'Text layer disagrees'}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600 ring-1 ring-slate-200">
              <ScanLine size={11} /> Scanned – no text layer
            </span>
          )}
        </div>
      }
    >
      {info?.fallback_reason && <div className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200">Live call failed, cached result used: {info.fallback_reason}</div>}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <Field label="Vendor" value={ex.vendor_name} conf={conf.vendor_name} />
        <Field label="Vendor GSTIN" value={ex.vendor_gstin} conf={conf.vendor_gstin} found={f('vendor_gstin')} mono />
        <Field label="Invoice no." value={ex.invoice_number} conf={conf.invoice_number} found={f('invoice_number')} mono hint={ex.invoice_number_normalised ? `normalised: ${ex.invoice_number_normalised}` : undefined} />
        <Field label="Invoice date" value={fmtDate(ex.invoice_date)} conf={conf.invoice_date} />
        <Field label="PO number" value={ex.po_number ?? (ex.po_reference_text ? undefined : 'none printed')} conf={conf.po_number} mono hint={ex.po_reference_text ? `“${ex.po_reference_text}”` : undefined} />
        <Field label="Due / terms" value={[fmtDate(ex.due_date), ex.payment_terms].filter(x => x && x !== '—').join(' · ')} />
        <Field label="Bank on invoice" value={ex.vendor_bank?.bank_name ? `${ex.vendor_bank.bank_name} · ${ex.vendor_bank.account_number ?? ''}` : null} conf={conf.vendor_bank} mono hint={ex.vendor_bank?.ifsc ? `IFSC ${ex.vendor_bank.ifsc}` : undefined} />
        <Field label="Bill to" value={ex.bill_to_name} />
      </div>
      {ex.notes && <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600 ring-1 ring-slate-200"><b>Note on invoice:</b> {ex.notes}</div>}

      <div className="mt-4 overflow-x-auto scroll-thin">
        <table className="w-full min-w-[420px] text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wide text-slate-500">
              <th className="py-1.5 pr-2 font-medium">Line item</th>
              <th className="px-2 text-right font-medium">Qty</th>
              <th className="px-2 text-right font-medium">Unit price</th>
              <th className="pl-2 text-right font-medium">Amount</th>
            </tr>
          </thead>
          <tbody className="tabular">
            {ex.line_items.map((l, i) => (
              <tr key={i} className="border-b border-slate-100">
                <td className="py-1.5 pr-2">{l.description}{l.hsn && <span className="ml-1.5 text-[11px] text-slate-400">HSN {l.hsn}</span>}</td>
                <td className="px-2 text-right">{fmtQty(l.quantity)} <span className="text-[11px] text-slate-400">{l.uom}</span></td>
                <td className="px-2 text-right">{fmtINR(l.unit_price)}</td>
                <td className="pl-2 text-right">{fmtINR(l.amount)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot className="tabular text-[13px]">
            <tr><td colSpan={3} className="pt-2 text-right text-slate-500">{ex.prices_tax_inclusive ? 'Taxable value (rates include GST)' : 'Subtotal'}</td><td className="pt-2 text-right">{fmtINR(ex.subtotal)}</td></tr>
            {ex.tax_lines.map((t, i) => (
              <tr key={i}><td colSpan={3} className="text-right text-slate-500">{t.type} {t.rate ? `@ ${Number(t.rate)}%` : ''}</td><td className="text-right">{fmtINR(t.amount)}</td></tr>
            ))}
            <tr className="font-semibold text-slate-900"><td colSpan={3} className="pt-1 text-right">Total <ConfBadge value={conf.total} /></td><td className="pt-1 text-right">{fmtINR(ex.total)}</td></tr>
          </tfoot>
        </table>
      </div>
      {(info?.warnings?.length ?? 0) > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-amber-800">{info!.warnings!.map((w, i) => <li key={i}>⚠ {w}</li>)}</ul>
      )}
    </Card>
  )
}
