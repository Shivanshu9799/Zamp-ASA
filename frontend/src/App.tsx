import { useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { Check, RotateCcw } from 'lucide-react'
import { api } from './api'
import type { AppConfig } from './types'
import { Button, Modal, cx } from './components/ui'
import Dashboard from './pages/Dashboard'
import NewRun from './pages/NewRun'
import RunView from './pages/RunView'
import MasterData from './pages/MasterData'

function Header() {
  const nav = useNavigate()
  const [cfg, setCfg] = useState<AppConfig | null>(null)
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api.config().then(setCfg).catch(() => {}) }, [])
  const reset = async () => {
    setBusy(true)
    try { await api.reset() } finally { setBusy(false); setConfirm(false); nav('/'); window.location.reload() }
  }
  const link = ({ isActive }: { isActive: boolean }) => cx('rounded-lg px-3 py-1.5 text-sm font-medium transition', isActive ? 'bg-indigo-50 text-indigo-800' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900')
  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-[1280px] items-center justify-between gap-4 px-4 py-2.5 sm:px-6">
        <div className="flex items-center gap-6">
          <NavLink to="/" className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-700 text-white"><Check size={18} strokeWidth={3} /></span>
            <span className="leading-tight"><span className="block text-sm font-semibold text-slate-900">Invoice Agent</span><span className="block text-[11px] text-slate-500">{cfg?.buyer.name ?? 'Accounts payable'}</span></span>
          </NavLink>
          <nav className="flex items-center gap-1">
            <NavLink to="/" end className={link}>Dashboard</NavLink>
            <NavLink to="/new" className={link}>New run</NavLink>
            <NavLink to="/master" className={link}>Master data</NavLink>
          </nav>
        </div>
        <div className="flex items-center gap-3">
          {cfg && <span className="hidden text-[11px] text-slate-400 md:inline" title={`Model ${cfg.llm.model}`}>Extraction: {cfg.llm.mode}{cfg.llm.api_key_configured ? '' : ' · pre-recorded'}</span>}
          <Button variant="secondary" className="!py-1.5 text-xs" onClick={() => setConfirm(true)}><RotateCcw size={13} /> Reset demo</Button>
        </div>
      </div>
      <Modal open={confirm} onClose={() => setConfirm(false)} title="Reset the demo?" footer={<><Button variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button><Button variant="danger" disabled={busy} onClick={reset}>{busy ? 'Resetting…' : 'Reset'}</Button></>}>
        This deletes every run, approval and audit entry you created, then reloads the master data and the three seeded historical invoices.
      </Modal>
    </header>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Header />
      <main className="mx-auto max-w-[1280px] px-4 py-6 sm:px-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/new" element={<NewRun />} />
          <Route path="/runs/:id" element={<RunView />} />
          <Route path="/master" element={<MasterData />} />
          <Route path="*" element={<div className="py-20 text-center text-sm text-slate-500">Page not found</div>} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
