# Demo script

Before you record or present: open the app, click **Reset demo**, then keep the **Dashboard** tab handy. Everything runs from **New run → sample gallery** (one click each). Each run takes about 4 seconds on screen because of the deliberate pause between stages.

## 5-minute video

| Time | What you do | What you say |
|---|---|---|
| **0:00 – 0:30** Problem | Dashboard (3 seeded invoices). | "AP teams re-key invoices, check them against the PO and the warehouse receipt by eye, and the expensive mistakes are the quiet ones: paying twice, paying the wrong account, paying for goods that never arrived. This agent does the reading and the checking, shows its work, and a person only handles the exceptions." |
| **0:30 – 2:00** Happy path (90 s) | New run → **Happy path** → Run. Watch the stepper. Click **Extract**, then **PO match** to expand. Point at the PDF beside the extracted fields (confidence badges, green ✓ "found in PDF text"). Scroll to the match table and the "What was checked" list. | "Eight stages, live. The AI reads the PDF — the badge says whether that read was live or cached — and code cross-checks it against the PDF's own text. From stage 3 on there is no AI: vendor by GSTIN, bank account vs master, duplicate check, and a three-way match — invoice vs PO vs goods received. Approved, with every check and its evidence on screen. And note the wording: *recommended for payment* — the system never releases money." |
| **2:00 – 3:00** Split PO (60 s) | Run **Split PO 1/3 → 2/3 → 3/3** quickly (the first two approve). On 3/3 show the amber decision, the red **+3 over open qty** cell and the **PO balance bar**. Show the draft email → Copy. | "One PO, delivered and billed in three parts. Each invoice is fine on its own; the third bills 33 units when only 30 are left — over by 3 units, ₹1,500 over the PO. Two rules fire, both listed, and it drafts the email to the vendor asking for a credit note." |
| **3:00 – 4:00** Edge case (60 s) | Pick one: **Scanned duplicate** *(run Happy path first)* → show it is image-only and that the file hash differs, yet it is **Rejected** with "duplicate of run #…". *Or* **No PO number** → candidate list → decoy shown as excluded → **Confirm PO** → Approve. | "Same invoice, re-sent as a scan with the number retyped and a later date. A hash check would miss it; the fuzzy duplicate rule catches it. Rejected, with the reason." *(Or: "No PO number — the agent suggests PO-1003, shows why, and a human confirms. The same-value PO of another vendor is excluded: amount alone is never enough.")* |
| **4:00 – 5:00** Dashboard + principle (60 s) | Dashboard: KPIs, top exception reasons, filter to Pending, open the bank-change run if you have time. | "Throughput, auto-approval rate, ₹ on hold, and why things get held. The design choice I'd defend to a CFO: **AI reads and explains, code decides.** The model can be wrong; the rules can't be talked into anything. Every decision cites rule IDs and evidence, and any override needs a reason and lands in the audit log." |

## Full interview run order

1. **Reset demo.**
2. **01 Happy path** — APPROVE. Show the stepper, cross-check, 3-way table.
3. **02 Happy path (service)** — APPROVE. Different layout; IGST vs CGST+SGST; 2-way match.
4. **03a** → **03b** → **03c** — APPROVE, APPROVE, PENDING (R12 + R13). PO balance bar; Master data → Purchase orders shows ₹45,000 billed and ₹16,500 *in review*.
5. **04 No PO number** — PENDING (R10), candidates with reasons, PO-2026-1009 shown excluded → **Confirm PO** → APPROVE; open the audit trail.
6. **05 Scanned duplicate** — REJECT (R08). (Requires step 2.)
7. **06 Bank change** — PENDING, **security hold**. Read the next action: "verify with the vendor via the phone number *on file*, not the contact on the invoice."
8. Dashboard: auto-approval rate (never counts the human-confirmed one), top exception reasons, filters.
9. Master data → Rules & tolerances: walk the precedence line.

## Questions to be ready for
* **"What if the AI misreads a number?"** Cross-check against the text layer; confidence threshold; line math and totals must reconcile (R03); anything doubtful is Pending, not Approved.
* **"Why not let the model decide?"** Not reproducible, not auditable, and prompt-injectable — an invoice can contain text. The model only sees the document and, later, the check results to word them.
* **"Scanned invoice with no text layer?"** The model reads the image; the cross-check is reported as unavailable (not as a pass) and the confidence threshold carries the load.
* **"Where does it stop?"** Recommends and drafts; humans approve exceptions; payment runs, GL coding and ERP posting are next steps.
* **"Is the reading really done by an AI?"** Yes — the sample extractions are real `gemini-3.5-flash-lite` output, cached by file hash so the demo is repeatable (the badge reads *LLM (cached)*). Upload any other invoice and the same model reads it live (*LLM (live)*). The rules never see the model's opinion, only its structured fields.
