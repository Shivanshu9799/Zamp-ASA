import { ReactNode, useEffect } from 'react'
import { AlertTriangle, CheckCircle2, Loader2, ShieldAlert, XCircle } from 'lucide-react'
import type { RunStatus } from '../types'

export function cx(...a: (string | false | null | undefined)[]) {
  return a.filter(Boolean).join(' ')
}

const PILL: Record<string, { cls: string; label: string; icon: ReactNode }> = {
  APPROVED: { cls: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20', label: 'Approved', icon: <CheckCircle2 size={13} /> },
  PENDING: { cls: 'bg-amber-50 text-amber-800 ring-amber-600/25', label: 'Pending review', icon: <AlertTriangle size={13} /> },
  REJECTED: { cls: 'bg-rose-50 text-rose-700 ring-rose-600/20', label: 'Rejected', icon: <XCircle size={13} /> },
  PROCESSING: { cls: 'bg-sky-50 text-sky-700 ring-sky-600/20', label: 'Processing', icon: <Loader2 size={13} className="animate-spin" /> },
}

export function StatusPill({ status, hold, size = 'sm' }: { status: RunStatus; hold?: boolean; size?: 'sm' | 'lg' }) {
  const p = PILL[status] ?? PILL.PENDING
  return (
    <span className={cx('inline-flex items-center gap-1.5 rounded-full font-medium ring-1 ring-inset whitespace-nowrap', p.cls, size === 'lg' ? 'px-3.5 py-1.5 text-sm' : 'px-2.5 py-0.5 text-xs')}>
      {hold && status === 'PENDING' ? <ShieldAlert size={size === 'lg' ? 15 : 13} /> : p.icon}
      {hold && status === 'PENDING' ? 'Security hold' : p.label}
    </span>
  )
}

export function Card({ title, right, children, className, pad = true }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={cx('rounded-xl bg-white shadow-card ring-1 ring-slate-200/80', className)}>
      {title && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
          {right}
        </header>
      )}
      <div className={pad ? 'p-5' : ''}>{children}</div>
    </section>
  )
}

export function Button({ variant = 'secondary', className, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'success' | 'ghost' }) {
  const v = {
    primary: 'bg-indigo-700 text-white hover:bg-indigo-800 shadow-sm',
    secondary: 'bg-white text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50',
    danger: 'bg-white text-rose-700 ring-1 ring-rose-300 hover:bg-rose-50',
    success: 'bg-emerald-600 text-white hover:bg-emerald-700 shadow-sm',
    ghost: 'text-slate-600 hover:bg-slate-100',
  }[variant]
  return <button {...p} className={cx('inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50', v, className)} />
}

export function Modal({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode }) {
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-[1px]" onClick={onClose} />
      <div className="relative w-full max-w-md animate-rise rounded-2xl bg-white p-6 shadow-2xl ring-1 ring-slate-200">
        <h3 className="text-base font-semibold text-slate-900">{title}</h3>
        <div className="mt-3 text-sm text-slate-600">{children}</div>
        {footer && <div className="mt-5 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500">
      <Loader2 size={16} className="animate-spin" /> {label ?? 'Loading…'}
    </div>
  )
}

export function Empty({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-14 text-center">
      <div className="text-sm font-medium text-slate-700">{title}</div>
      {hint && <div className="max-w-sm text-sm text-slate-500">{hint}</div>}
      {action}
    </div>
  )
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-800 ring-1 ring-rose-200">
      <span>{message}</span>
      {onRetry && <Button variant="danger" onClick={onRetry}>Retry</Button>}
    </div>
  )
}

export function RuleTag({ id }: { id: string }) {
  return <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] font-medium text-slate-500">{id}</span>
}

export function ConfBadge({ value }: { value: number | undefined }) {
  if (value === undefined) return null
  const low = value < 0.8
  return (
    <span className={cx('rounded px-1.5 py-0.5 text-[10px] font-semibold tabular', low ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-500')}>
      {low ? 'Low · ' : ''}{Math.round(value * 100)}%
    </span>
  )
}
