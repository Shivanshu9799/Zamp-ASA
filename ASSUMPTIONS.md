# Assumptions

Where the brief was silent or ambiguous I picked the sensible option and wrote it down here.

## Scope and data
1. **INR and Indian GST only.** One buyer entity (Meridian Foods Pvt. Ltd., Maharashtra, state code 27). Intra-state supply → CGST + SGST; inter-state → IGST alone. The buyer's GSTIN is synthetic.
2. **All data is synthetic**: vendors, POs, goods receipts and invoices. PO and GRN data comes from a spreadsheet-like master (CSV seeded into the database), not an ERP.
3. **Three extra historical POs** (PO-2026-0905, -0911, -0918, dated August/September, with two goods receipts) were added to the seed data so that three seeded history invoices can be real approved runs on the dashboard. They do not touch any scenario PO, so the seed data for the eight scenarios is exactly as specified.
4. **Seeded history is processed by the real pipeline** at first boot / reset and back-dated 2–6 days, so the dashboard looks lived-in without any fake rows. One of them uses GST-**inclusive** prices to exercise that path.
5. PO amounts are **pre-tax**. "Invoiced to date" and cumulative checks compare the invoice's pre-tax (taxable) value; for tax-inclusive invoices the taxable value is derived by removing GST from the line rates.

## Decisions and tolerances
6. **APPROVE is a recommendation to post for payment**, never a payment release.
7. **Tolerances** (all in `config.py`, shown in the UI): price ±1 % (typical rounding/rate-card noise, small enough to catch a re-priced line); arithmetic rounding ₹1.00 (paise-level rounding across lines and GST); quantity tolerance 0 (no over-billing on goods); vendor name 92 % auto / 80 % review; PO suggestion at score ≥ 0.75; duplicate window 10 days; extraction confidence ≥ 0.80.
8. **"Invoiced to date" counts only approved invoices** (system or human). Pending invoices are displayed as "in review" against the PO but are not counted, so a held invoice cannot block a valid one.
9. **3-way match uses all goods receipts recorded so far**, not only those dated before the invoice. Received qty − previously invoiced qty is the billable balance per PO line.
10. **R07 (exact duplicate) is a literal match** — same vendor and the same invoice number as printed (case/space-insensitive). Format variants (`INV-SGI-0418` vs `INVSGI418`, zero-padding) are deliberately left to **R08**, because the brief expects the scanned re-submission to be caught by R08. The normalised form is what R08 compares.
11. **R08 needs the same total for every non-file-hash signal.** Sequential numbers from one vendor (APX-1101 / -1102) look 86 % alike, so number similarity alone must never flag a duplicate. *High* = identical file, or number ≥ 85 % + same total + dates within 10 days (→ Reject). *Medium* = same total plus either a similar number or a close date (→ Pending).
12. **R05 with a GSTIN that is on file but a very different name** is sent to review rather than rejected. A name that matches but a GSTIN that is not on file is also sent to review.
13. **R09 on a missing/wrong PO is a note, R10 is the failing rule.** Inference never auto-selects a PO: it always lands in Pending with a suggestion, and a human confirms.
14. **PO inference** scores only the vendor's *open* POs (vendor match is a hard gate, not a weight): item description 35 %, quantity & price 25 %, amount 20 %, date proximity to any date quoted in the invoice text 20 %. Other vendors' POs with the same value are shown as *excluded* so the "amount alone is not enough" point is visible.
15. A **scanned** invoice has no text layer, so the cross-check is "not available" (a note, not a failure); the confidence threshold still applies.
16. **Auto-approved %** on the dashboard = invoices the rules approved that no human touched (no PO confirmation, override or re-run).
17. **Processing time** shown is compute time summed over the stages. The ~450 ms pause between stages exists only so the live stepper is watchable and is excluded from the figure.
18. **Human actions** are unauthenticated apart from the optional shared password; the actor is recorded as `finance.user`.

## LLM usage
19. **The committed extraction cache is real model output** (`gemini-3.5-flash-lite`, produced with `scripts_warm_cache.py --live`), one file per sample PDF, keyed by the PDF's SHA-256 and labelled *LLM (cached)* in the UI. Running the real model exposed a brittleness the hand-written ground truth had hidden (it merged a "Service period" note into a line description), which is why line/PO description matching tolerates extra text. Anthropic is supported as an alternative provider but has not been run against the real API.
23. **A duplicate is not matched against the PO.** When R07, or R08 at high confidence, rejects an invoice, R10–R14 are shown as *skipped* ("Not evaluated – invoice is a duplicate of run #N"): they would only restate the original invoice's quantities and balances, and must not appear as separate reasons to reject. R09 (is the PO valid) is still evaluated. A *medium*-confidence R08 (Pending) does **not** skip matching.
24. **Free-tier limits.** The Gemini free tier of the chosen model allows roughly 15 requests/min and 500/day; the warm-up script paces itself and retries 429/503 with back-off. If a live call still fails, extraction falls back to the cache when one exists, otherwise the run goes to Pending with the reason.
20. In `cached` mode a cache miss calls the API if a key exists (so arbitrary uploads still work); without a key the stage fails gracefully and the run goes to Pending with the reason.
21. Explanations are template-generated unless a key is configured (they are then cached under `llm_cache/explain_*.json`); LLM text is accepted only if every number in it already appears in the check results.
22. The pipeline treats the model's confidence as advisory: it is lowered to 0.5 automatically for any field the PDF text layer contradicts.

## Hardening after an external review
25. **R16 (addressee) was added** beyond the original 15 rules: a valid PO number is not proof that the invoice is addressed to Meridian Foods, so a bill-to name that is < 80 % similar goes to Pending. A missing bill-to name is a note, not a failure (scans).
26. **R03 always reconciles the total.** If the subtotal or tax total could not be read, the lines and tax lines are used instead; if neither is possible the check fails closed. A line without quantity or unit price cannot have qty × price verified (recorded in the evidence), but the totals must still add up.
27. **R04 with several GST slabs** compares the *total* tax with Σ (line taxable value × line rate) and sums CGST/SGST across slabs; with no subtotal printed it falls back to the sum of the lines.
28. **R02:** a critical field for which the reader reported no confidence counts as 0.5 (low), not as a pass. The text-layer cross-check compares numbers as Decimals, so `61,000`, `61,000.00` and `Rs. 61,000/-` all match.
29. **One PO line can be billed on several invoice lines** (e.g. two lots). A second line maps to the same PO line only on a ≥ 85 % description match, and R12 compares the *sum* of those lines with the open quantity.
30. **Concurrency:** stages 5–8 run under one process-wide lock (see README). The demo reset waits for in-flight runs.
31. **Not changed, by design:** (a) when R05 fails but a vendor is suggested (borderline name, GSTIN mismatch) the suggested vendor is still used for the later stages so the reviewer sees its bank, duplicate and PO findings — the run is Pending regardless because R05 failed, and *Confirm PO* does not clear that; (b) overriding or rejecting an invoice does not automatically re-evaluate other invoices already decided — balances are as of the moment each invoice was processed, and *Re-run* refreshes one; (c) a human who approves an over-billed or duplicate invoice makes it count towards the PO balance, which is recorded in the audit log.
32. **Model id:** `gemini-3.5-flash-lite` is a real, working model for the key used here (it appears in AI Studio's rate-limit page and all 11 sample extractions were produced with it). It is configurable via `LLM_MODEL`.

## Not built (on purpose)
GL coding, approval matrices, payment runs, FX, credit notes, email intake, ERP integration, real user accounts. They are listed as next steps in the README.
