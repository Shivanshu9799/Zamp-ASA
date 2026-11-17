import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileUp, Loader2, Play, ScanLine } from 'lucide-react'
import { api } from '../api'
import type { Sample } from '../types'
import { fmtINR } from '../lib/format'
import { Button, Card, ErrorBox, Spinner, cx } from '../components/ui'

const TONE: Record<string, string> = {
  APPROVE: 'bg-emerald-50 text-emerald-700 ring-emerald-200', PENDING: 'bg-amber-50 text-amber-800 ring-amber-200', REJECT: 'bg-rose-50 text-rose-700 ring-rose-200',
}
const EXP: Record<string, string> = { APPROVE: 'Expect: approve', PENDING: 'Expect: pending', REJECT: 'Expect: reject' }

export default function NewRun() {
  const nav = useNavigate()
  const [samples, setSamples] = useState<Sample[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState('')
  const [drag, setDrag] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => { api.samples().then(setSamples).catch(e => setErr(e.message)) }, [])

  const go = async (key: string, fn: () => Promise<{ run_id: number }>) => {
    setBusy(key); setErr('')
    try { nav(`/runs/${(await fn()).run_id}`) } catch (e: any) { setErr(e.message); setBusy(null) }
  }
  const upload = (f?: File | null) => {
    if (!f) return
    if (!f.name.toLowerCase().endsWith('.pdf')) return setErr('Please choose a PDF file.')
    go('upload', () => api.createFromFile(f))
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">Process an invoice</h1>
        <p className="text-sm text-slate-500">Upload a vendor invoice PDF (digital or scanned), or run one of the sample invoices. You will watch each stage as it happens.</p>
      </div>
      {err && <ErrorBox message={err} />}

      <div
        onDragOver={e => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files?.[0]) }}
        onClick={() => input.current?.click()}
        className={cx('flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed bg-white px-6 py-12 text-center transition', drag ? 'border-indigo-500 bg-indigo-50/50' : 'border-slate-300 hover:border-indigo-400 hover:bg-slate-50')}
      >
        {busy === 'upload' ? <Loader2 className="animate-spin text-indigo-600" size={28} /> : <FileUp size={28} className="text-indigo-600" />}
        <div className="text-sm font-medium text-slate-800">Drop an invoice PDF here, or click to browse</div>
        <div className="text-xs text-slate-500">PDF up to 15 MB · scanned images are fine</div>
        <input ref={input} type="file" accept="application/pdf,.pdf" className="hidden" onChange={e => upload(e.target.files?.[0])} />
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold text-slate-800">Sample invoices</h2>
        {!samples ? <Spinner /> : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {samples.map(s => (
              <Card key={s.file} className="flex flex-col" pad={false}>
                <div className="flex flex-1 flex-col gap-2 p-4">
                  <div className="flex items-center justify-between gap-2">
                    <span className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-semibold text-indigo-700 ring-1 ring-indigo-200">{s.label}</span>
                    {s.scanned && <span className="inline-flex items-center gap-1 text-[11px] text-slate-500"><ScanLine size={12} /> scan</span>}
                  </div>
                  <div className="text-sm font-medium text-slate-900">{s.title}</div>
                  <p className="text-xs leading-relaxed text-slate-500">{s.blurb}</p>
                  <div className="mt-auto pt-2 text-xs text-slate-500">
                    <div className="truncate">{s.vendor}</div>
                    <div className="flex justify-between"><span className="font-mono">{s.invoice_number}</span><span className="font-medium tabular text-slate-700">{fmtINR(s.total)}</span></div>
                  </div>
                </div>
                <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2.5">
                  <span className={cx('rounded-full px-2 py-0.5 text-[10px] font-medium ring-1', TONE[s.expected])}>{EXP[s.expected]}</span>
                  <Button variant="primary" className="!py-1.5 text-xs" disabled={!!busy} onClick={() => go(s.file, () => api.createFromSample(s.file))}>
                    {busy === s.file ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />} Run
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        )}
        <p className="mt-3 text-xs text-slate-400">Tip: for the story to make sense, run “Happy path” before “Scanned duplicate”, and the three “Split PO” invoices in order.</p>
      </div>
    </div>
  )
}
