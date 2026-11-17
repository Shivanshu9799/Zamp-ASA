import type { LineMatch, POBalance } from '../types'
import { fmtINR, fmtQty, num } from '../lib/format'
import { Card, cx } from './ui'

function Cell({ children, bad, ok, className }: { children: React.ReactNode; bad?: boolean; ok?: boolean; className?: string }) {
  return <td className={cx('px-3 py-2 text-right', bad && 'bg-rose-50 font-semibold text-rose-700', className)}>{children}</td>
}

export function MatchTable({ lines, poId }: { lines: LineMatch[]; poId: string | null }) {
  const goods = lines.some(l => l.received_qty !== null)
  return (
    <Card title={<>Invoice vs purchase order {poId && <span className="ml-1 font-mono text-xs font-normal text-slate-500">{poId}</span>}</>} pad={false}>
      <div className="overflow-x-auto scroll-thin">
        <table className="w-full min-w-[620px] text-[13px] tabular">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/70 text-[11px] uppercase tracking-wide text-slate-500">
              <th className="px-3 py-2 text-left font-medium">Invoice line</th>
              <th className="px-3 py-2 text-right font-medium">PO qty</th>
              {goods && <th className="px-3 py-2 text-right font-medium">Received</th>}
              <th className="px-3 py-2 text-right font-medium">Billed before</th>
              <th className="px-3 py-2 text-right font-medium">This invoice</th>
              <th className="px-3 py-2 text-right font-medium">PO price</th>
              <th className="px-3 py-2 text-right font-medium">Invoice price</th>
            </tr>
          </thead>
          <tbody>
            {lines.map(l => {
              const over = l.qty_ok === false && l.qty_delta !== null && num(l.qty_delta) > 0
              const priceBad = l.price_ok === false
              return (
                <tr key={l.line} className="border-b border-slate-100 align-top">
                  <td className="px-3 py-2">
                    {l.description}
                    <div className="text-[11px] text-slate-500">{l.po_line_no ? `PO line ${l.po_line_no}: ${l.po_description}` : <span className="font-medium text-rose-600">Not on the PO</span>}</div>
                  </td>
                  <Cell>{fmtQty(l.ordered_qty)}</Cell>
                  {goods && <Cell>{fmtQty(l.received_qty)}</Cell>}
                  <Cell>{fmtQty(l.previously_invoiced_qty)}</Cell>
                  <Cell bad={l.qty_ok === false}>
                    {fmtQty(l.this_qty)}
                    {goods && l.open_qty !== null && <div className="text-[11px] font-normal text-slate-500">open: {fmtQty(l.open_qty)}</div>}
                    {over && <div className="text-[11px] font-semibold text-rose-700">+{fmtQty(l.qty_delta)} over open qty</div>}
                  </Cell>
                  <Cell>{fmtINR(l.po_unit_price)}</Cell>
                  <Cell bad={priceBad}>
                    {fmtINR(l.inv_unit_price)}
                    {l.price_delta_pct !== null && Math.abs(num(l.price_delta_pct)) > 0 && <div className="text-[11px] font-normal">{num(l.price_delta_pct) > 0 ? '+' : ''}{l.price_delta_pct}%</div>}
                  </Cell>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {!goods && <div className="border-t border-slate-100 px-4 py-2 text-xs text-slate-500">Service PO: two-way match (invoice vs PO). No goods receipt is needed.</div>}
    </Card>
  )
}

export function POBalanceBar({ b }: { b: POBalance }) {
  const po = num(b.po_amount)
  const inv = num(b.invoiced_to_date)
  const cur = num(b.this_invoice)
  const rev = num(b.in_review)
  const over = num(b.over_by)
  const scale = Math.max(po, inv + cur) || 1
  const pct = (x: number) => `${Math.max(0, (x / scale) * 100)}%`
  const fit = Math.max(0, Math.min(cur, po - inv))
  return (
    <Card title={<>PO balance <span className="ml-1 font-mono text-xs font-normal text-slate-500">{b.po_id}</span></>}>
      <div className="relative">
        <div className="flex h-5 w-full overflow-hidden rounded-md bg-slate-100 ring-1 ring-slate-200">
          <div className="bg-slate-700" style={{ width: pct(inv) }} title="Invoiced to date" />
          <div className={over > 0 ? 'bg-amber-500' : 'bg-indigo-600'} style={{ width: pct(fit) }} title="This invoice" />
          {over > 0 && <div className="bg-rose-600" style={{ width: pct(over) }} title="Over the PO" />}
          {rev > 0 && over <= 0 && <div className="hatch" style={{ width: pct(Math.min(rev, Math.max(po - inv - cur, 0))) }} title="In review (not counted)" />}
        </div>
        {over > 0 && (
          <div className="absolute top-[-4px] h-7 border-l-2 border-dashed border-slate-900" style={{ left: pct(po) }}>
            <span className="absolute -top-4 -translate-x-1/2 whitespace-nowrap text-[10px] font-medium text-slate-600">PO value</span>
          </div>
        )}
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <Legend color="bg-slate-700" label="Invoiced to date" value={fmtINR(b.invoiced_to_date)} />
        <Legend color={over > 0 ? 'bg-amber-500' : 'bg-indigo-600'} label="This invoice" value={fmtINR(b.this_invoice)} />
        <Legend color="bg-slate-200" label={over > 0 ? 'Over PO by' : 'Remaining after'} value={over > 0 ? fmtINR(b.over_by) : fmtINR(b.remaining_after)} danger={over > 0} />
        <Legend color="bg-slate-100" label="PO value (ex-GST)" value={fmtINR(b.po_amount)} />
      </dl>
      <p className="mt-3 text-xs text-slate-500">Only approved invoices count as “invoiced to date”. Invoices still in review{rev > 0 ? ` (${fmtINR(b.in_review)})` : ''} are shown for information but not counted.</p>
    </Card>
  )
}

function Legend({ color, label, value, danger }: { color: string; label: string; value: string; danger?: boolean }) {
  return (
    <div>
      <dt className="flex items-center gap-1.5 text-xs text-slate-500"><span className={cx('h-2.5 w-2.5 rounded-sm', color)} />{label}</dt>
      <dd className={cx('mt-0.5 font-semibold tabular', danger ? 'text-rose-700' : 'text-slate-900')}>{value}</dd>
    </div>
  )
}
