# Aastha CRM — Phase 1 UAT Checklist

Run this on a real development machine with PostgreSQL through `docker compose up --build` before clinic production use.

## A. Authentication / Permissions
- Reception can create Leads/Patients/Visits and consultation bills/payments.
- Reception cannot see bulk export, legacy import, audit, or master approval screens.
- Super Reception can open Master Approvals but cannot legacy-import or bulk export.
- Admin can legacy-import, review audit, and perform authorized finance corrections.
- Doctor can view Patient/Visits and authorize Complimentary; Doctor cannot receive payment.

## B. Lead / Appointment
- Create Lead with mandatory source.
- Search same name/mobile and confirm previous inquiries appear.
- New genuine inquiry can still be created.
- Mark Lost and Reopen same Lead ID.
- Set DNC and confirm outbound assignment/export/API rejects it.
- Book appointment and verify no UHID is generated.
- Try same doctor/time twice and confirm overlap is blocked.

## C. Patient Identity
- Convert Lead to Patient only after registration confirmation.
- Double-click/retry Convert and confirm only one Patient/UHID exists.
- Create two family members with same mobile and confirm both search results appear.
- Confirm no automatic Patient selection by mobile.
- Before Visit creation verify Name + Age/Gender + UHID confirmation is required.

## D. Maker–Checker
- Reception proposes missing Locality; registration continues immediately.
- Reception proposes missing Chief Complaint; Visit continues immediately.
- Super Reception sees both pending items.
- Test Approve, Correct, Merge.
- Referenced pending item cannot be simply Rejected; system should require Correct/Merge instead.
- After Merge, linked Patient/Visit points to canonical master.

## E. Legacy Patient Import
- Upload provided CSV template.
- Upload XLSX equivalent.
- Confirm incomplete rows become `LEGACY_INCOMPLETE`.
- Confirm a duplicate row shows `DUPLICATE_REVIEW`.
- Resolve duplicate as Link Existing, Create Separate, or Skip.
- Add financial-looking columns (`outstanding`, `paid_amount`, `gst`) and confirm they are reported as ignored and are absent from staged safe patient data.
- Commit import and confirm global UHIDs are generated for new Patients.
- Confirm import is visible in audit history.

## F. Consultation Finance
- Configure effective consultation fee.
- New Consultation → Paid Consultation Required.
- Create draft → Finalize → sequential unique Bill Number.
- Run two simultaneous finalizations and confirm no duplicate bill number.
- Receive Cash/UPI/Card and print receipt.
- Print consultation bill.
- Full payment creates one 10-day Patient-level free-follow-up entitlement.
- Different complaint within window still uses the same Patient entitlement.
- Use free follow-up once; second return in same window becomes chargeable.
- Two terminals cannot consume the same entitlement twice.
- Doctor Complimentary requires Doctor login.
- Reception cannot convert a finalized paid visit to Complimentary.

## G. Finance Corrections / Audit
- Reception requests a financial correction where applicable.
- Admin sees pending request and resolves it.
- Change payment mode after finalization as Admin with reason.
- Verify audit shows old value, new value, actor, timestamp, reason.
- Void unpaid finalized bill and confirm Bill Number is retained and never reused.
- Confirm paid bill cannot be voided through the Phase 1 workflow.

## H. Concurrency / Data Integrity
- Two users edit same Lead; stale save is rejected.
- Two users edit same Patient; stale save is rejected.
- Concurrent UHID/bill allocation produces different numbers.
- Database UNIQUE constraint catches any attempted duplicate business number.

## I. Integration Boundaries
- Voice/WhatsApp/third-party uses API, never direct database access.
- Appointment API does not generate UHID.
- DNC Lead never enters outbound AI/calling export.
- Internal Admin reporting may still show DNC with DNC flag preserved.

## Go-Live Gate
Production use should start only after all critical UAT cases above pass on real PostgreSQL and the seeded development passwords are replaced.

## Procedure Finance / Inventory bridge UAT
- [ ] Doctor can create a Procedure Order from a Patient Visit.
- [ ] Reception can view Procedure Orders but cannot create/execute them.
- [ ] New Procedure Order starts `NOT_BILLED` and emits Finance outbox event.
- [ ] Procedure session creation is blocked until external Finance returns `CLEARED` or `COMPLIMENTARY`.
- [ ] A Procedure Execution cannot be created without a real Procedure Visit for the same Patient.
- [ ] Rendering Branch must equal the Procedure Visit branch.
- [ ] Starting a session changes linked Visit to `IN_PROGRESS`.
- [ ] Completing a session changes linked Visit to `COMPLETED`.
- [ ] Completing a session emits one Inventory event containing no Patient identity.
- [ ] Inventory event uses Rendering Branch, not ordering/sales branch.
- [ ] Completing one session marks order `PARTIALLY_COMPLETED`, not `COMPLETED`.
- [ ] Doctor can explicitly close an order after at least one completed session.
- [ ] Order with a completed session cannot be cancelled; it must be closed instead.
- [ ] Finance callback duplicate `external_event_id` is idempotent.
- [ ] Reusing the same Finance event ID for another Procedure Order is rejected.
- [ ] Integration clients cannot read another organization's procedure data.
