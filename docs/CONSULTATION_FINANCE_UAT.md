# Module 6 — Consultation Billing & Payments

Module 5's Visit save, Patient history and Visit Register were accepted by the clinic before this milestone.

## Admin setup

Open Consultation Finance → Fee and follow-up configuration. Save the real consultation fee, scope (all or specific branch/Doctor) and effective date. No clinic fee has been invented. Save the follow-up policy if changing the current default: ten days and one free use per qualifying paid consultation. A new version affects future entitlements; existing entitlements retain their recorded window and allowed uses. Zero days or zero uses disables new free entitlement creation under that policy.

For fee precedence: Doctor+branch > Doctor > branch > global, then newest effective version. Fee changes never change amounts already copied into bills. New-year document series are created under an organization lock and allocated under a row lock; historic numbers/counters are retained. Receipt numbers are unique and sequential within the branch/fiscal-year series. Historical receipts keep their existing UUID reference when they predate this migration.

## Reception check

1. Create a Consultation Visit with a Doctor. In Visits → Details, choose Open Consultation Finance, or open Consultation Finance from the menu.
2. Confirm Name, Age/Gender and UHID shown on that card. This is required before bill creation, free follow-up and collection. If the Doctor was left unassigned, choose the verified consulting Doctor before billing. Assignment is locked after any financial record and must match a linked appointment.
3. Select Create Bill → review amount → confirm identity again → Finalize Bill. A unique bill number appears. Printing a draft is blocked.
4. Confirm identity, choose Cash/UPI/Card/Other and enter amount. Receive Payment. Check the saved receipt number, amount, paid total and balance.
5. Try a partial payment, then the remaining balance using another mode. Each collection has its own receipt; overpayment is rejected. Print Bill and each Print Receipt from the card. Reopen the page: receipts remain available.
6. If a payment response is interrupted, use Recover Payment on the same browser tab/session, including after reload. It resends the original request and returns the same saved receipt. Do not start a new collection until the original result is resolved. The server also deduplicates request IDs and rejects changed-payload reuse.
7. Full collection creates Paid clearance and a Patient-level entitlement. Create a later Visit within its window with any complaint; choose Use Free Follow-Up. The same entitlement cannot be consumed twice. The completed Visit's Patient/UHID and clinical records are retained.
8. Date/branch/Doctor filters show allowed Visits and collections. The queue pages through 100 Visit records; the daily totals aggregate all matching collections, including partial payments. India time is used.

## Doctor and Admin checks

- Doctor uses their own login and assigned Visit to authorize complimentary, before finalized billing. Reception cannot impersonate this approval. Complimentary creates no payment/paid entitlement.
- A finalized/partly paid/paid bill cannot be turned complimentary. Post-payment refunds and credit notes remain outside Phase 1.
- Admin corrections require reason and row version. Paid bills cannot be voided. Review BILL_DRAFT_CREATED, BILL_FINALIZED, PAYMENT_RECORDED, FREE_FOLLOWUP_USED and COMPLIMENTARY_AUTHORISED audit events.
- Branch/org boundaries apply to decisions, documents, collections, corrections, reports and Doctor assignment. Read-only access does not grant cashier or configuration rights.

## Release gate

Migration 0010 adds nullable payment request/hash/receipt fields and optional policy organization scope. It never rewrites historical amounts, payments, UHIDs or counters. CI validates populated migration preservation and full-content backup/restore for consultation financial tables, PostgreSQL concurrent collection/number/follow-up races, rollback after an injected failure, browser payment recovery and print documents, production web/Docker builds.

Before deployment download a fresh clinic database backup (frozen rule 138). Deploy API then web on the canonical Phase 1 Render services, with auto-deploy off. Do not downgrade this migration on a database that has collected under Module 6. User clinic acceptance follows deployment; automated tests are not a substitute for staff testing with their assigned logins.
