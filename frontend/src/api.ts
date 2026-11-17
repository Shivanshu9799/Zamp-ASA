import type { AppConfig, RunDetail, RunSummary, Sample, Stats } from './types'

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {}
    throw new Error(msg)
  }
  return res.json()
}

export const api = {
  runs: (p: { status?: string; vendor?: string; q?: string; page?: number; page_size?: number } = {}) => {
    const qs = new URLSearchParams()
    Object.entries(p).forEach(([k, v]) => v !== undefined && v !== '' && qs.set(k, String(v)))
    return fetch(`/api/runs?${qs}`).then(r => j<{ items: RunSummary[]; total: number; page: number; page_size: number }>(r))
  },
  run: (id: number | string) => fetch(`/api/runs/${id}`).then(r => j<RunDetail>(r)),
  createFromSample: (sample: string) =>
    fetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sample }) }).then(r => j<{ run_id: number }>(r)),
  createFromFile: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return fetch('/api/runs', { method: 'POST', body: fd }).then(r => j<{ run_id: number }>(r))
  },
  action: (id: number, body: { type: 'approve' | 'reject' | 'confirm_po' | 'rerun'; po_id?: string; reason?: string }) =>
    fetch(`/api/runs/${id}/actions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(r => j<RunDetail>(r)),
  stats: () => fetch('/api/dashboard/stats').then(r => j<Stats>(r)),
  master: <T = any>(kind: 'vendors' | 'pos' | 'grns') => fetch(`/api/master/${kind}`).then(r => j<T[]>(r)),
  samples: () => fetch('/api/samples').then(r => j<Sample[]>(r)),
  config: () => fetch('/api/config').then(r => j<AppConfig>(r)),
  reset: () => fetch('/api/demo/reset', { method: 'POST' }).then(r => j<{ ok: boolean }>(r)),
}
