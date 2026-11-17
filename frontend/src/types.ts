export type RunStatus = 'PROCESSING' | 'APPROVED' | 'PENDING' | 'REJECTED'
export type StageStatus = 'pending' | 'running' | 'passed' | 'warning' | 'failed' | 'skipped'

export interface RunSummary {
  id: number
  created_at: string
  finished_at: string | null
  status: RunStatus
  decision: 'APPROVE' | 'PENDING' | 'REJECT' | null
  security_hold: boolean
  source: string
  file_name: string
  vendor_id: string | null
  vendor_name: string | null
  invoice_number: string | null
  invoice_date: string | null
  po_id: string | null
  total: string | null
  net_amount: string | null
  reason: string | null
  fired_rules: string[]
  duration_ms: number | null
  scanned: boolean
}

export interface Check {
  rule_id: string
  name: string
  stage: string
  status: 'pass' | 'warn' | 'fail' | 'skipped'
  severity: 'reject' | 'security' | 'pending' | 'info'
  evidence: Record<string, any>
  message: string
}

export interface StageRow {
  stage: string
  seq: number
  status: StageStatus
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  summary: string
  checks: Check[]
  details: Record<string, any>
}

export interface Extracted {
  vendor_name: string | null
  vendor_gstin: string | null
  vendor_address: string | null
  vendor_bank: { bank_name: string | null; account_number: string | null; ifsc: string | null }
  bill_to_name: string | null
  invoice_number: string | null
  invoice_number_normalised: string | null
  invoice_date: string | null
  due_date: string | null
  payment_terms: string | null
  po_number: string | null
  po_reference_text: string | null
  currency: string
  line_items: { description: string; sku: string | null; hsn: string | null; quantity: string | null; uom: string | null; unit_price: string | null; amount: string | null; tax_rate: string | null }[]
  subtotal: string | null
  tax_lines: { type: string; rate: string | null; amount: string | null }[]
  tax_total: string | null
  other_charges: string
  total: string | null
  prices_tax_inclusive: boolean
  field_confidence: Record<string, number>
  notes: string | null
}

export interface LineMatch {
  line: number
  description: string
  match_score: number
  this_qty: string | null
  inv_unit_price: string | null
  inv_amount: string | null
  po_line_no: number | null
  po_description: string | null
  ordered_qty: string | null
  po_unit_price: string | null
  received_qty: string | null
  previously_invoiced_qty: string | null
  open_qty: string | null
  qty_delta: string | null
  price_delta_pct: string | null
  price_ok: boolean | null
  qty_ok: boolean | null
  uom?: string
}

export interface POBalance {
  po_id: string
  po_amount: string
  invoiced_to_date: string
  this_invoice: string
  remaining_before: string
  remaining_after: string
  in_review: string
  over_by: string
}

export interface Candidate {
  po_id: string
  score: number
  po_date?: string
  po_amount: string
  type?: string
  parts?: Record<string, number>
  reasons: string[]
  excluded?: boolean
  vendor_id?: string
}

export interface NextAction {
  type: string
  title: string
  channel: string
  to: string | null
  subject: string | null
  body: string
  note: string | null
}

export interface AuditEntry {
  id: number
  ts: string
  actor: string
  action: string
  reason: string | null
  details: Record<string, any>
}

export interface RunDetail extends RunSummary {
  file_meta: { filename: string; sha256: string; size_bytes: number; pages: number; has_text_layer: boolean; kind: string } | null
  extracted: Extracted | null
  extraction_info: {
    source: 'llm_live' | 'llm_cached' | 'seed_cached'
    model: string
    fallback_reason?: string
    crosscheck?: { available: boolean; agreed: boolean | null; fields: Record<string, { llm: string | null; found_in_text: boolean }>; note: string }
    warnings?: string[]
  } | null
  stages: StageRow[]
  decision_detail: { decision?: string; security_hold?: boolean; primary_reason?: string; fired_rules?: string[]; warning_rules?: string[]; passed_rules?: string[] }
  explanation: string | null
  explanation_source: string | null
  next_action: NextAction | null
  line_matches: LineMatch[] | null
  po_balance: POBalance | null
  po_candidates: { candidates: Candidate[]; excluded: Candidate[]; reference_dates: string[] } | null
  po_override: string | null
  duplicate_of: number | null
  error: string | null
  audit: AuditEntry[]
}

export interface StageEvent {
  run_id: number
  stage: string
  label: string
  seq: number
  status: StageStatus
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  summary: string
  details: Record<string, any>
}

export interface Stats {
  processed: number
  by_status: Record<string, number>
  value_by_status: Record<string, string>
  auto_approval_rate: number
  auto_approved: number
  avg_processing_ms: number
  top_exception_reasons: { rule_id: string; label: string; count: number }[]
  security_holds: number
}

export interface Sample {
  file: string
  label: string
  group: string
  title: string
  expected: string
  order: number
  blurb: string
  scanned: boolean
  total: string
  vendor: string
  invoice_number: string
}

export interface AppConfig {
  tolerances: Record<string, string | number>
  rules: { id: string; stage: string; name: string; on_fail: string; plain: string }[]
  stages: { key: string; label: string }[]
  buyer: { name: string; state_code: string; gstin: string }
  llm: { mode: string; model: string; api_key_configured: boolean }
  po_inference_weights: Record<string, number>
}
